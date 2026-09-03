"""Deterministic capability routing and explainable provider selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .policy import Policy, PolicyDecision
from .registry import CapabilitySpec, ModelSpec


class RoutingError(ValueError):
    """Raised when no provider/model satisfies the request constraints."""

    def __init__(self, message: str, explanation: dict[str, Any] | None = None):
        super().__init__(message)
        self.explanation = explanation or {}


@dataclass(frozen=True)
class RouteCandidate:
    capability: str
    provider: str
    model: str
    quality: float
    latency_ms: int
    memory_mb: int
    local: bool
    commercial: bool
    available: bool
    score: float | None = None
    reasons: tuple[str, ...] = ()
    policy: PolicyDecision | None = None

    @property
    def allowed(self) -> bool:
        return self.available and bool(self.policy is None or self.policy.allowed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "provider": self.provider,
            "model": self.model,
            "quality": self.quality,
            "estimated_latency_ms": self.latency_ms,
            "memory_mb": self.memory_mb,
            "local": self.local,
            "commercial": self.commercial,
            "available": self.available,
            "allowed": self.allowed,
            "score": self.score,
            "reasons": list(self.reasons) + ([] if self.policy is None else list(self.policy.reasons)),
        }


class DeterministicRouter:
    """Select a provider using registry facts and explicit policy only.

    There is deliberately no model call in this path. The same registry,
    policy and installed state produce the same route on every invocation.
    """

    def __init__(self, *, policy: Policy, specs: dict[str, CapabilitySpec], providers: dict[str, Any], installations=None, benchmarks=None, hardware=None):
        self.policy = policy
        self.specs = specs
        self.providers = providers
        self.installations = installations or {}
        self.benchmarks = benchmarks
        self.hardware = hardware or {}

    @staticmethod
    def _quality(model: ModelSpec) -> float:
        value = getattr(model, "quality", None)
        if value is not None:
            return max(0.0, min(1.0, float(value)))
        # Registry files predating quality measurements remain routable with a
        # conservative score and a stable recommendation bias.
        return 0.82 if model.recommended else 0.80

    @staticmethod
    def _latency(provider: Any, model: ModelSpec) -> int:
        value = getattr(provider, "latency_ms", None)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
        return max(20, int(model.memory_mb * 0.08))

    def _measured_latency(self, capability: str, provider: Any, model: ModelSpec) -> int | None:
        if self.benchmarks is None:
            return None
        provider_name = getattr(provider, "name", "")
        values = self.benchmarks.list(capability)
        matching = [item for item in values if item.get("provider") == provider_name and item.get("model") == model.id]
        if self.hardware:
            def same_hardware(item):
                observed = item.get("hardware") or {}
                return all(not self.hardware.get(key) or not observed.get(key) or observed.get(key) == self.hardware.get(key) for key in ("os", "architecture", "cpu"))
            hardware_matches = [item for item in matching if same_hardware(item)]
            matching = hardware_matches or matching
        values = [item.get("warm_latency_ms") or item.get("latency_ms") for item in matching]
        values = [value for value in values if isinstance(value, (int, float)) and value >= 0]
        return int(min(values)) if values else None

    def _candidate(self, capability: str, spec: CapabilitySpec, provider: Any, model: ModelSpec, rule: dict[str, Any]) -> RouteCandidate:
        installation = self.installations.get(capability)
        reasons: list[str] = []
        available = provider is not None
        if provider is None:
            reasons.append("provider adapter is not registered")
        if installation and installation.get("model") and installation.get("model") != model.id:
            available = False
            reasons.append(f"installed model is pinned to {installation['model']}")
        if getattr(provider, "requires_verified_artifact", False) and not installation:
            # The runtime may install a registered artifact lazily. Keep the
            # candidate routable while exposing its unconfigured state in the
            # explanation; execution still fails closed if installation fails.
            reasons.append("verified model artifact will be installed lazily")
        local = not bool(getattr(provider, "remote", False) or getattr(provider, "node_id", None))
        provider_name = getattr(provider, "name", spec.provider) if provider is not None else spec.provider
        latency = self._measured_latency(capability, provider, model) if provider is not None else None
        latency = self._latency(provider, model) if latency is None and provider is not None else (latency or 0)
        policy = self.policy.evaluate(capability=capability, provider=provider or object(), model=model, options=rule, estimated_latency_ms=latency)
        if rule.get("commercial_safe") and not spec.commercial:
            reasons.append("capability weights are not marked commercial-safe")
            policy = PolicyDecision(False, tuple(policy.reasons) + ("capability weights are not marked commercial-safe",))
        profile = str(rule.get("profile", self.policy.default_profile))
        weights = {
            "fast": (0.6, 1.6, 0.4),
            "balanced": (1.0, 0.8, 0.3),
            "quality": (1.7, 0.3, 0.15),
            "ultra": (2.2, 0.15, 0.1),
        }.get(profile, (1.0, 0.8, 0.3))
        score = round(weights[0] * self._quality(model) - weights[1] * latency / 1000 - weights[2] * model.memory_mb / 4096, 6)
        return RouteCandidate(capability, provider_name, model.id, self._quality(model), latency, model.memory_mb, local, spec.commercial, available, score, tuple(reasons), policy)

    def route(self, capability: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if capability not in self.specs:
            raise RoutingError(f"unknown capability '{capability}'")
        spec = self.specs[capability]
        options = options if isinstance(options, dict) else {}
        rule = self.policy.resolve(capability, options)
        provider_options = []
        primary = self.providers.get(capability)
        if primary is not None:
            provider_options.append(primary)
        for provider_name in spec.providers:
            alternate = self.providers.get(f"{capability}@{provider_name}") or self.providers.get(provider_name)
            if alternate is not None and alternate not in provider_options:
                provider_options.append(alternate)
        for key, alternate in self.providers.items():
            if key.startswith(f"{capability}@") and alternate not in provider_options:
                provider_options.append(alternate)
        if not provider_options:
            provider_options = [None]
        models = list(spec.models)
        installation = self.installations.get(capability)
        requested_model = options.get("model")
        if requested_model:
            models = [model for model in models if model.id == str(requested_model)]
            if not models:
                raise RoutingError(f"model '{requested_model}' is not registered for {capability}")
        elif installation and installation.get("model"):
            models = [model for model in models if model.id == installation["model"]] or models
        candidates = [self._candidate(capability, spec, provider, model, rule) for provider in provider_options for model in models]
        eligible = [item for item in candidates if item.allowed]
        selected = sorted(eligible, key=lambda item: (-float(item.score or 0), item.provider, item.model))[0] if eligible else None
        explanation = {
            "requested": {"capability": capability, "options": dict(options)},
            "profile": rule.get("profile"),
            "constraints": rule,
            "candidates": [item.to_dict() for item in candidates],
            "rejected": [item.to_dict() for item in candidates if not item.allowed],
            "selected": selected.to_dict() if selected else None,
        }
        if selected is None:
            raise RoutingError(f"no provider satisfies policy for {capability}", explanation)
        explanation["reason"] = "highest deterministic utility score; ties are resolved by provider and model name"
        return explanation
