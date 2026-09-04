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
    def _quality(model: ModelSpec, provider: Any = None) -> float:
        provider_quality = getattr(provider, "quality", None)
        if isinstance(provider_quality, (int, float)) and not isinstance(provider_quality, bool):
            return max(0.0, min(1.0, float(provider_quality)))
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
        if installation and installation.get("model") and installation.get("provider") == getattr(provider, "name", spec.provider) and installation.get("model") != model.id:
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
        commercial = bool(getattr(provider, "commercial", spec.commercial))
        if rule.get("commercial_safe") and not commercial:
            reasons.append("provider or weights are not marked commercial-safe")
            policy = PolicyDecision(False, tuple(policy.reasons) + ("provider or weights are not marked commercial-safe",))
        profile = str(rule.get("profile", self.policy.default_profile))
        weights = {
            "fast": (0.6, 1.6, 0.4),
            "balanced": (1.0, 0.8, 0.3),
            "quality": (1.7, 0.3, 0.15),
            "ultra": (2.2, 0.15, 0.1),
        }.get(profile, (1.0, 0.8, 0.3))
        provider_memory = getattr(provider, "memory_requirement_mb", None)
        memory_mb = int(provider_memory) if provider_memory is not None else model.memory_mb
        score = round(weights[0] * self._quality(model, provider) - weights[1] * latency / 1000 - weights[2] * memory_mb / 4096, 6)
        if getattr(provider, "preferred_model", None) == model.id:
            score += 0.000001
        return RouteCandidate(capability, provider_name, model.id, self._quality(model, provider), latency, memory_mb, local, commercial, available, score, tuple(reasons), policy)

    def route(self, capability: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if capability not in self.specs:
            raise RoutingError(f"unknown capability '{capability}'")
        spec = self.specs[capability]
        options = options if isinstance(options, dict) else {}
        rule = self.policy.resolve(capability, options)
        requested_provider = options.get("provider")
        if requested_provider is not None and (not isinstance(requested_provider, str) or not requested_provider.strip()):
            raise RoutingError("provider must be a non-empty string")
        provider_options = []
        primary = self.providers.get(capability)
        if primary is not None and (not requested_provider or getattr(primary, "name", None) == requested_provider):
            provider_options.append(primary)
        for provider_name in spec.providers:
            alternate = self.providers.get(f"{capability}@{provider_name}") or self.providers.get(provider_name)
            if alternate is not None and (not requested_provider or getattr(alternate, "name", None) == requested_provider) and alternate not in provider_options:
                provider_options.append(alternate)
        for key, alternate in self.providers.items():
            if key.startswith(f"{capability}@") and (not requested_provider or getattr(alternate, "name", None) == requested_provider) and alternate not in provider_options:
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
        candidates = []
        for provider in provider_options:
            provider_models = models
            # An installed model pins only the provider that owns it. An
            # alternate provider must keep its own model identity so a local
            # fallback can never relabel the primary provider (or vice versa).
            if (
                not requested_model
                and installation
                and installation.get("model")
                and installation.get("provider") == getattr(provider, "name", spec.provider)
            ):
                provider_models = [model for model in models if model.id == installation["model"]] or models
            preferred_model = getattr(provider, "preferred_model", None)
            # Provider adapters may expose a stable model identity that is
            # different from the capability's primary model (for example the
            # real OS TTS fallback). Keep candidates honest so routing and
            # result provenance never label one provider as another model.
            if not requested_model and preferred_model:
                preferred = [model for model in models if model.id == preferred_model]
                if preferred:
                    provider_models = preferred
            candidates.extend(self._candidate(capability, spec, provider, model, rule) for model in provider_models)
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
