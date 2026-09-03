"""Explicit specialist cascade execution for confidence-aware escalation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CascadeError(ValueError):
    """Raised when a cascade specification is invalid."""


@dataclass(frozen=True)
class CascadeStep:
    capability: str
    options: dict[str, Any] = field(default_factory=dict)
    min_confidence: float | None = None


class SpecialistCascade:
    def __init__(self, steps=None, name: str = "specialist-cascade"):
        self.name = name
        self.steps: list[CascadeStep] = []
        for item in steps or []:
            self.add(**item) if isinstance(item, dict) else self.add(item)

    def add(self, capability: str, *, options=None, min_confidence: float | None = None) -> "SpecialistCascade":
        if not isinstance(capability, str) or not capability.strip():
            raise CascadeError("cascade capability must be a non-empty string")
        if min_confidence is not None and not 0 <= float(min_confidence) <= 1:
            raise CascadeError("min_confidence must be between 0 and 1")
        self.steps.append(CascadeStep(capability.strip(), dict(options or {}), float(min_confidence) if min_confidence is not None else None))
        return self

    def execute(self, runtime, input_path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.steps:
            raise CascadeError("cascade must contain at least one step")
        traces = []
        last = None
        for index, step in enumerate(self.steps):
            result = runtime.run(step.capability, input_path, {**(options or {}), **step.options})
            last = result
            confidence = result.get("confidence") if isinstance(result, dict) else None
            threshold = step.min_confidence
            if threshold is None:
                threshold = (options or {}).get("min_confidence")
            accepted = not result.get("error") and (threshold is None or (confidence is not None and float(confidence) >= float(threshold)))
            traces.append({"step": index, "capability": result.get("capability", step.capability), "provider": result.get("provider"), "model": result.get("model"), "confidence": confidence, "threshold": threshold, "accepted": accepted, "error": result.get("error")})
            if accepted:
                result.setdefault("trace", []).append({"stage": "cascade", "name": self.name, "steps": traces})
                return result
        if last is None:
            raise CascadeError("cascade produced no result")
        last.setdefault("trace", []).append({"stage": "cascade", "name": self.name, "steps": traces})
        if last.get("error") is None:
            last.setdefault("warnings", []).append("cascade exhausted before reaching its confidence threshold")
        return last
