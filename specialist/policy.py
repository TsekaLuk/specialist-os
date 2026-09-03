"""Deterministic capability policy and profile resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any


class PolicyError(ValueError):
    """Raised when an operator policy cannot be parsed safely."""


PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "fast": {"max_latency_ms": 500, "max_memory_mb": 2048, "min_confidence": 0.0},
    "balanced": {"max_latency_ms": None, "max_memory_mb": None, "min_confidence": 0.70},
    "quality": {"max_latency_ms": None, "max_memory_mb": None, "min_confidence": 0.85},
    "ultra": {"max_latency_ms": None, "max_memory_mb": None, "min_confidence": 0.95},
}


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class Policy:
    default_profile: str = "balanced"
    local_first: bool = True
    allow_remote: bool = False
    fallback: bool = True
    local_only: bool = False
    max_latency_ms: int | None = None
    min_confidence: float | None = None
    max_memory_mb: int | None = None
    commercial_safe: bool = False
    privacy: str = "local_first"
    capability_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    profiles: dict[str, dict[str, Any]] = field(default_factory=lambda: {key: dict(value) for key, value in PROFILE_DEFAULTS.items()})
    source: str = "defaults"

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, source: str = "mapping") -> "Policy":
        if not isinstance(value, dict):
            raise PolicyError("policy must be an object")
        policy_section = value.get("policy") if isinstance(value.get("policy"), dict) else value
        hardware = policy_section.get("hardware") if isinstance(policy_section.get("hardware"), dict) else {}
        quality = policy_section.get("quality") if isinstance(policy_section.get("quality"), dict) else {}
        cost = policy_section.get("cost") if isinstance(policy_section.get("cost"), dict) else {}
        profile = str(policy_section.get("default_profile") or quality.get("default_profile") or "balanced")
        if profile not in PROFILE_DEFAULTS:
            raise PolicyError(f"unknown default profile '{profile}'")
        max_memory = hardware.get("max_memory_mb")
        if max_memory is None and hardware.get("max_memory_percent") is not None:
            # Percent limits require runtime hardware data and are retained for
            # the router through the capability rule map.
            max_memory = None
        if max_memory is not None:
            max_memory = _positive_int(max_memory, "hardware.max_memory_mb")
        min_confidence = quality.get("min_confidence")
        if min_confidence is not None:
            min_confidence = _confidence(min_confidence, "quality.min_confidence")
        capability_rules = value.get("capabilities") or value.get("rules") or {}
        if not isinstance(capability_rules, dict):
            raise PolicyError("capabilities policy must be an object")
        for name, settings in capability_rules.items():
            if not isinstance(name, str) or not isinstance(settings, dict):
                raise PolicyError("each capability policy rule must be an object")
        profiles = {key: dict(defaults) for key, defaults in PROFILE_DEFAULTS.items()}
        custom_profiles = value.get("profiles") or {}
        if not isinstance(custom_profiles, dict):
            raise PolicyError("profiles must be an object")
        for name, settings in custom_profiles.items():
            if not isinstance(name, str) or not isinstance(settings, dict):
                raise PolicyError("each profile must be an object")
            profiles[name] = {**profiles.get(name, {}), **settings}
        return cls(
            default_profile=profile,
            local_first=bool(policy_section.get("local_first", True)),
            allow_remote=bool(policy_section.get("allow_remote", False)),
            fallback=bool(policy_section.get("fallback", True)),
            local_only=bool(policy_section.get("local_only", False)),
            max_latency_ms=_positive_int(policy_section["max_latency_ms"], "max_latency_ms") if policy_section.get("max_latency_ms") is not None else None,
            min_confidence=min_confidence,
            max_memory_mb=max_memory,
            commercial_safe=bool(policy_section.get("commercial_safe", cost.get("commercial_safe", False))),
            privacy=str(policy_section.get("privacy", "local_first")),
            capability_rules={str(name): dict(settings) for name, settings in capability_rules.items() if isinstance(settings, dict)},
            profiles=profiles,
            source=source,
        )

    @classmethod
    def load(cls, home: str | os.PathLike[str] | None = None, *, cwd: str | os.PathLike[str] | None = None) -> "Policy":
        candidates: list[Path] = []
        explicit = os.environ.get("SPECIALIST_POLICY_FILE")
        if explicit:
            candidates.append(Path(explicit).expanduser())
        if cwd:
            root = Path(cwd).expanduser()
            candidates.extend((root / "specialist.json", root / "specialist.yaml", root / ".specialist" / "policy.json"))
        if home:
            root = Path(home).expanduser()
            candidates.extend((root / "policy.json", root / "policy.yaml"))
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            try:
                text = path.read_text(encoding="utf-8")
                payload = json.loads(text)
            except (OSError, ValueError) as exc:
                # YAML is optional in the core distribution. A JSON-compatible
                # YAML file remains dependency-free and deterministic.
                try:
                    import yaml  # type: ignore

                    payload = yaml.safe_load(text)
                except Exception as yaml_exc:
                    raise PolicyError(f"could not parse policy {path}: {exc}") from yaml_exc
            return cls.from_mapping(payload or {}, source=str(path.resolve()))
        return cls()

    def resolve(self, capability: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options = options if isinstance(options, dict) else {}
        rule = dict(self.profiles.get(self.default_profile, PROFILE_DEFAULTS["balanced"]))
        capability_rule = {key: value for key, value in self.capability_rules.get(capability, {}).items() if value is not None}
        configured_profile = capability_rule.get("profile")
        if configured_profile:
            if str(configured_profile) not in self.profiles:
                raise PolicyError(f"unknown profile '{configured_profile}'")
            rule.update(self.profiles[str(configured_profile)])
            rule["profile"] = str(configured_profile)
        rule.update(capability_rule)
        explicit_profile = options.get("profile")
        if explicit_profile:
            name = str(explicit_profile)
            if name not in self.profiles:
                raise PolicyError(f"unknown profile '{name}'")
            rule.update(self.profiles[name])
            rule["profile"] = name
        rule.update({key: value for key, value in (options.get("constraints") or {}).items() if value is not None})
        rule.update({key: value for key, value in options.items() if key in {"local_only", "allow_remote", "fallback", "max_latency_ms", "min_confidence", "max_memory_mb", "commercial_safe"}})
        # Resolve these together so an explicit ``allow_remote`` option does
        # not accidentally inherit a contradictory local-only default.
        if "allow_remote" not in rule:
            rule["allow_remote"] = self.allow_remote
        if "local_only" not in rule:
            rule["local_only"] = self.local_only or not bool(rule["allow_remote"])
        rule.setdefault("fallback", self.fallback)
        rule.setdefault("profile", self.default_profile)
        return rule

    def evaluate(self, *, capability: str, provider: Any, model: Any, options: dict[str, Any] | None = None, estimated_latency_ms: int | None = None) -> PolicyDecision:
        rule = self.resolve(capability, options)
        reasons: list[str] = []
        is_remote = bool(getattr(provider, "remote", False) or getattr(provider, "node_id", None))
        if rule.get("local_only") and is_remote:
            reasons.append("remote provider is disallowed by local_only policy")
        if not rule.get("allow_remote", self.allow_remote) and is_remote:
            reasons.append("remote provider is disabled")
        max_latency = rule.get("max_latency_ms")
        if max_latency is not None and estimated_latency_ms is not None and int(estimated_latency_ms) > int(max_latency):
            reasons.append(f"estimated latency {estimated_latency_ms}ms exceeds {max_latency}ms")
        max_memory = rule.get("max_memory_mb")
        model_memory = getattr(model, "memory_mb", None)
        if max_memory is not None and model_memory is not None and int(model_memory) > int(max_memory):
            reasons.append(f"model memory {model_memory}MiB exceeds {max_memory}MiB")
        if rule.get("commercial_safe") and not bool(getattr(model, "commercial", True)):
            reasons.append("provider or weights are not marked commercial-safe")
        return PolicyDecision(not reasons, tuple(reasons))


def _positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) <= 0:
        raise PolicyError(f"{field_name} must be a positive integer")
    return int(value)


def _confidence(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise PolicyError(f"{field_name} must be between 0 and 1")
    return float(value)
