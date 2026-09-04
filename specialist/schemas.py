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
    observations: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)

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
    if not isinstance(value.get("observations", []), list) or not isinstance(value.get("evidence", []), list) or not isinstance(value.get("artifacts", []), list) or not isinstance(value.get("trace", []), list):
        raise ValueError("observation protocol fields must be arrays")
    if not isinstance(value.get("metrics", {}), dict) or not isinstance(value.get("provenance", {}), dict):
        raise ValueError("observation protocol metadata must be objects")
    confidence = value.get("confidence")
    if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError("confidence must be a finite number between 0 and 1 or null")
    for index, artifact in enumerate(value.get("artifacts", [])):
        if not isinstance(artifact, dict) or not isinstance(artifact.get("id"), str) or not isinstance(artifact.get("uri"), str):
            raise ValueError(f"artifacts[{index}] requires id and uri strings")
        if not isinstance(artifact.get("sha256"), str) or len(artifact["sha256"]) != 64:
            raise ValueError(f"artifacts[{index}].sha256 must be a SHA256 digest")
    # Error envelopes intentionally carry an empty result object. Only a
    # successful provider response is subject to the capability payload schema.
    if value["error"] is None:
        _validate_capability_result(value["capability"], value["result"])


def _array(result, key):
    value = result.get(key)
    if not isinstance(value, list):
        raise ValueError(f"result.{key} must be an array")
    return value


def _bbox(value, field):
    if not isinstance(value, list) or len(value) != 4 or any(not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item) for item in value):
        raise ValueError(f"{field} must contain four finite numbers")


def _timeline(result, key="segments"):
    for index, item in enumerate(_array(result, key)):
        if not isinstance(item, dict):
            raise ValueError(f"result.{key}[{index}] must be an object")
        start, end = item.get("start"), item.get("end")
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not math.isfinite(float(start)) or not math.isfinite(float(end)) or start < 0 or end < start:
            raise ValueError(f"result.{key}[{index}] has an invalid time range")


def _embedding(value, field="result.embedding", nullable=False):
    if value is None and nullable:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object" )
    artifact = value.get("artifact")
    if not isinstance(artifact, str) or not artifact.startswith("artifact://"):
        raise ValueError(f"{field}.artifact must be an artifact:// URI")
    dimension = value.get("dimension")
    if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
        raise ValueError(f"{field}.dimension must be a positive integer")


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
        mode = result["mode"].lower()
        if mode not in {"relative", "metric"}:
            raise ValueError("result.mode must be relative or metric")
        unit = result.get("unit")
        if mode == "relative" and unit is not None:
            raise ValueError("relative depth must not declare a distance unit")
        if mode == "metric" and unit != "meter":
            raise ValueError("metric depth must declare unit=meter")
        if mode == "metric" and result.get("estimated") is not True:
            raise ValueError("metric depth must declare estimated=true")
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
    elif capability in {"human.pose", "human.hand_landmarks", "human.face_landmarks", "human.gesture"}:
        key = {"human.pose": "persons", "human.hand_landmarks": "hands", "human.face_landmarks": "faces"}.get(capability)
        if key:
            _array(result, key)
        elif "gesture" not in result:
            raise ValueError("result.gesture is required")
    elif capability in {"speech.diarize", "speech.align_transcript", "speech.meeting"}:
        _timeline(result)
    elif capability == "audio.denoise":
        audio = result.get("audio")
        if not isinstance(audio, dict) or not isinstance(audio.get("artifact"), str) or not audio["artifact"].startswith("artifact://"):
            raise ValueError("result.audio.artifact is required")
        if result.get("profile") not in {"light", "balanced", "strong"}:
            raise ValueError("result.profile must be light, balanced, or strong")
    elif capability in {"vision.embed", "vision.embed_text"}:
        _embedding(result.get("embedding"))
    elif capability == "vision.similarity":
        score = result.get("score")
        if score is not None and (not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score)):
            raise ValueError("result.score must be a finite number or null")
    elif capability in {"vision.search", "vision.find_similar"}:
        _array(result, "results")
    elif capability == "identity.face.detect":
        _array(result, "faces")
    elif capability == "identity.face.embed":
        _embedding(result.get("embedding"), nullable=True)
    elif capability in {"identity.face.verify", "vision.face_compare"}:
        if result.get("match") is not None and not isinstance(result.get("match"), bool):
            raise ValueError("result.match must be boolean or null")
        threshold = result.get("threshold")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 <= threshold <= 1:
            raise ValueError("result.threshold must be between 0 and 1")
        if not isinstance(result.get("profile"), str):
            raise ValueError("result.profile is required")
    elif capability in {"vision.geometry.distance", "vision.geometry.angle", "vision.geometry.area", "vision.geometry.contour", "vision.geometry.homography", "vision.geometry.match_features", "vision.geometry.perspective_transform", "vision.geometry.calibrate_camera", "vision.geometry.solve_pnp", "vision.transform.crop", "vision.transform.resize", "vision.transform.rotate", "vision.transform.warp", "vision.transform.colorspace", "vision.transform.blur", "vision.transform.threshold", "media.probe", "media.video.extract_frames", "media.video.trim", "media.video.transcode", "media.video.concat", "media.audio.extract", "media.audio.trim", "media.audio.resample", "media.audio.convert", "media.audio.normalize", "media.transcribe_video", "vision.human_state", "vision.measure"}:
        if not isinstance(result, dict):
            raise ValueError("expanded capability result must be an object")
        if capability == "media.transcribe_video":
            if not isinstance(result.get("text"), str):
                raise ValueError("result.text must be a string")
            _timeline(result)
    elif capability in {"speech.synthesize", "speech.clone_voice"}:
        audio = result.get("audio")
        if not isinstance(audio, dict):
            raise ValueError("result.audio must be an object")
        artifact = audio.get("artifact")
        if not isinstance(artifact, str) or not artifact.startswith("artifact://"):
            raise ValueError("result.audio.artifact must be an artifact:// URI")
        mime = audio.get("mime")
        if not isinstance(mime, str) or not mime.startswith("audio/"):
            raise ValueError("result.audio.mime must be an audio MIME type")
        for key in ("duration_ms", "sample_rate"):
            value = audio.get(key)
            if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0):
                raise ValueError(f"result.audio.{key} must be a non-negative number or null")
        if capability == "speech.clone_voice" and not result.get("voice"):
            raise ValueError("result.voice is required for speech.clone_voice")
