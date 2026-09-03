"""Stable result envelope and JSON helpers.

Schemas are represented as dataclasses to keep the core dependency-free. The
wire format is deliberately boring JSON so it works for CLI, HTTP, MCP and
any generic LLM tool caller.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any


def json_safe(value):
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return json_safe(value.tolist())
    if hasattr(value, "item"):
        return json_safe(value.item())
    return str(value)


@dataclass
class InputInfo:
    type: str
    path: str
    size_bytes: int | None = None
    sha256: str | None = None


@dataclass
class PerformanceInfo:
    latency_ms: int = 0
    device: str = "cpu"
    cached: bool = False
    cold_start: bool = True


@dataclass
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultEnvelope:
    capability: str
    provider: str
    model: str
    input: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return json_safe(asdict(self))

    @classmethod
    def failure(cls, capability, provider, model, input_info, code, message, retryable=False, **details):
        return cls(
            capability=capability,
            provider=provider,
            model=model,
            input=input_info,
            error=asdict(ErrorInfo(code=code, message=message, retryable=retryable, details=details)),
        )


def validate_envelope(value: dict[str, Any]) -> None:
    """Validate the wire contract without requiring jsonschema at runtime."""
    required = {"capability", "provider", "model", "input", "result", "performance", "warnings", "error"}
    missing = required.difference(value)
    if missing:
        raise ValueError(f"result envelope missing keys: {sorted(missing)}")
    for key in ("capability", "provider", "model"):
        if not isinstance(value[key], str) or not value[key]:
            raise ValueError(f"result envelope field '{key}' must be a non-empty string")
    if not isinstance(value["input"], dict) or not isinstance(value["result"], dict) or not isinstance(value["performance"], dict):
        raise ValueError("result envelope input/result/performance must be objects")
    if not isinstance(value["warnings"], list) or any(not isinstance(item, str) for item in value["warnings"]):
        raise ValueError("result envelope warnings must be a string array")
    if value["error"] is not None and not isinstance(value["error"], dict):
        raise ValueError("result envelope error must be an object or null")
    if value["error"] is not None:
        error = value["error"]
        if not isinstance(error.get("code"), str) or not error.get("code") or not isinstance(error.get("message"), str):
            raise ValueError("result envelope error requires string code and message")
        return
    _validate_capability_result(value["capability"], value["result"])


def _array(result, key):
    value = result.get(key)
    if not isinstance(value, list):
        raise ValueError(f"result.{key} must be an array")
    return value


def _bbox(value, field):
    if not isinstance(value, list) or len(value) != 4 or any(not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item) for item in value):
        raise ValueError(f"{field} must contain four finite numbers")


def _validate_capability_result(capability: str, result: dict[str, Any]) -> None:
    if capability == "vision.detect":
        for index, item in enumerate(_array(result, "items")):
            if not isinstance(item, dict) or not isinstance(item.get("label"), str):
                raise ValueError(f"result.items[{index}] requires a string label")
            _bbox(item.get("bbox"), f"result.items[{index}].bbox")
            confidence = item.get("confidence")
            if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence)):
                raise ValueError(f"result.items[{index}].confidence must be a finite number or null")
    elif capability == "vision.segment":
        for index, item in enumerate(_array(result, "masks")):
            if not isinstance(item, dict) or not isinstance(item.get("polygon"), list):
                raise ValueError(f"result.masks[{index}].polygon must be an array")
    elif capability == "vision.ocr":
        for index, item in enumerate(_array(result, "blocks")):
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError(f"result.blocks[{index}] requires string text")
            _bbox(item.get("bbox"), f"result.blocks[{index}].bbox")
            confidence = item.get("confidence")
            if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence)):
                raise ValueError(f"result.blocks[{index}].confidence must be a finite number or null")
    elif capability == "vision.depth":
        if not isinstance(result.get("width"), int) or not isinstance(result.get("height"), int) or result["width"] <= 0 or result["height"] <= 0:
            raise ValueError("result.width and result.height must be positive integers")
        if not isinstance(result.get("mode"), str):
            raise ValueError("result.mode must be a string")
    elif capability == "screen.parse":
        _array(result, "elements")
    elif capability == "document.parse":
        if not isinstance(result.get("markdown"), str):
            raise ValueError("result.markdown must be a string")
        for key in ("tables", "figures", "formulas"):
            _array(result, key)
        if result.get("pages") is not None and (not isinstance(result["pages"], int) or result["pages"] < 0):
            raise ValueError("result.pages must be a non-negative integer or null")
    elif capability == "audio.transcribe":
        if not isinstance(result.get("text"), str):
            raise ValueError("result.text must be a string")
        _array(result, "segments")
    elif capability == "audio.vad":
        for index, item in enumerate(_array(result, "segments")):
            if not isinstance(item, dict) or not isinstance(item.get("start"), (int, float)) or not isinstance(item.get("end"), (int, float)):
                raise ValueError(f"result.segments[{index}] requires numeric start and end")
            if item["start"] < 0 or item["end"] < item["start"]:
                raise ValueError(f"result.segments[{index}] has an invalid time range")
        duration = result.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration < 0:
            raise ValueError("result.duration_seconds must be a non-negative finite number")
