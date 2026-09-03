"""Provider-independent confidence and verification primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


def clamp(value: float | int | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def agreement(values: Iterable[Any]) -> float | None:
    normalized = [value for value in values if value is not None]
    if len(normalized) < 2:
        return None
    first = normalized[0]
    matches = sum(value == first for value in normalized[1:])
    return round(matches / (len(normalized) - 1), 6)


def combine(model_confidence: float | None, *, provider_agreement: float | None = None, input_quality: float | None = None, historical_accuracy: float | None = None) -> float | None:
    values = [item for item in (clamp(model_confidence), clamp(provider_agreement), clamp(input_quality), clamp(historical_accuracy)) if item is not None]
    if not values:
        return None
    weights = [0.55, 0.2, 0.1, 0.15]
    present = [(value, weights[index]) for index, value in enumerate((model_confidence, provider_agreement, input_quality, historical_accuracy)) if value is not None]
    total = sum(weight for _, weight in present)
    return round(sum(clamp(value) * weight for value, weight in present) / total, 6)


@dataclass(frozen=True)
class VerificationPolicy:
    mode: str = "none"
    threshold: float = 0.8

    def should_verify(self, confidence: float | None) -> bool:
        if self.mode == "none":
            return False
        if self.mode == "confidence_threshold":
            return confidence is None or float(confidence) < self.threshold
        return self.mode in {"dual_provider", "deterministic_check"}
