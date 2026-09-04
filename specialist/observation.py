"""Specialist Observation Protocol helpers.

The protocol keeps model-specific payloads in ``result`` while exposing a
stable list of observations, evidence, artifacts and provenance for agents and
debugging tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any


@dataclass(frozen=True)
class Evidence:
    provider: str
    model: str
    confidence: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"provider": self.provider, "model": self.model}
        if self.confidence is not None:
            value["confidence"] = float(self.confidence)
        if self.details:
            value["details"] = dict(self.details)
        return value


@dataclass(frozen=True)
class Provenance:
    source: dict[str, Any]
    provider: str
    model_version: str
    runtime_version: str
    transformations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": dict(self.source),
            "provider": self.provider,
            "model_version": self.model_version,
            "runtime_version": self.runtime_version,
            "transformations": list(self.transformations),
        }


@dataclass(frozen=True)
class Observation:
    id: str
    type: str
    value: Any
    geometry: dict[str, Any] | None = None
    confidence: float | None = None
    evidence: tuple[Evidence, ...] = ()
    provenance: Provenance | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"id": self.id, "type": self.type, "value": self.value}
        if self.geometry is not None:
            value["geometry"] = self.geometry
        if self.confidence is not None:
            value["confidence"] = float(self.confidence)
        if self.evidence:
            value["evidence"] = [item.to_dict() for item in self.evidence]
        if self.provenance is not None:
            value["provenance"] = self.provenance.to_dict()
        return value


def _finite_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return max(0.0, min(1.0, float(value)))
    return None


def _observation_id(capability: str, index: int, value: Any, geometry: Any) -> str:
    payload = json.dumps({"capability": capability, "index": index, "value": value, "geometry": geometry}, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "obs_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _base_evidence(provider: str, model: str, confidence: float | None) -> tuple[Evidence, ...]:
    return (Evidence(provider=provider, model=model, confidence=confidence),)


def build_observations(capability: str, result: dict[str, Any], *, provider: str, model: str, source: dict[str, Any], runtime_version: str) -> list[dict[str, Any]]:
    """Normalize known provider payloads into deterministic observations."""
    provenance = Provenance(source=source, provider=provider, model_version=model, runtime_version=runtime_version)
    records: list[Observation] = []

    def add(index: int, kind: str, value: Any, geometry: dict[str, Any] | None, confidence: Any) -> None:
        normalized = _finite_confidence(confidence)
        records.append(Observation(_observation_id(capability, index, value, geometry), kind, value, geometry, normalized, _base_evidence(provider, model, normalized), provenance))

    if capability == "vision.detect":
        for index, item in enumerate(result.get("items") or []):
            if isinstance(item, dict):
                add(index, "entity", item.get("label"), {"bbox": item.get("bbox")}, item.get("confidence"))
    elif capability == "vision.segment":
        for index, item in enumerate(result.get("masks") or []):
            if isinstance(item, dict):
                add(index, "region", item.get("label") or "segment", {"polygon": item.get("polygon")}, item.get("confidence"))
    elif capability == "vision.ocr":
        for index, item in enumerate(result.get("blocks") or []):
            if isinstance(item, dict):
                add(index, "text_region", item.get("text", ""), {"bbox": item.get("bbox")}, item.get("confidence"))
    elif capability == "vision.depth":
        add(0, "depth_map", {"width": result.get("width"), "height": result.get("height"), "mode": result.get("mode")}, None, result.get("confidence"))
    elif capability == "screen.parse":
        for index, item in enumerate(result.get("elements") or []):
            if isinstance(item, dict):
                geometry = {"bbox": item.get("bbox")} if item.get("bbox") is not None else None
                add(index, "gui_element", item, geometry, item.get("confidence"))
    elif capability == "document.parse":
        add(0, "document", {"pages": result.get("pages"), "markdown_chars": len(result.get("markdown") or "")}, None, result.get("confidence"))
    elif capability == "audio.transcribe":
        segments = result.get("segments") or []
        for index, item in enumerate(segments):
            if isinstance(item, dict):
                geometry = {"start": item.get("start"), "end": item.get("end")}
                add(index, "speech_segment", item.get("text", ""), geometry, item.get("confidence"))
        if not segments and result.get("text"):
            add(0, "transcript", result.get("text"), None, result.get("confidence"))
    elif capability == "audio.vad":
        for index, item in enumerate(result.get("segments") or []):
            if isinstance(item, dict):
                add(index, "speech_interval", item, {"start": item.get("start"), "end": item.get("end")}, item.get("confidence"))
    elif capability in {"speech.synthesize", "speech.clone_voice"}:
        audio = result.get("audio") or {}
        if isinstance(audio, dict) and audio.get("artifact"):
            add(0, "audio_artifact", {"artifact": audio.get("artifact"), "mime": audio.get("mime"), "duration_ms": audio.get("duration_ms"), "sample_rate": audio.get("sample_rate"), "voice": result.get("voice")}, None, 1.0)
    elif capability in {"human.pose", "human.hand_landmarks", "human.face_landmarks"}:
        key = {"human.pose": "persons", "human.hand_landmarks": "hands", "human.face_landmarks": "faces"}[capability]
        for index, item in enumerate(result.get(key) or []):
            if isinstance(item, dict):
                add(index, key[:-1], item, None, item.get("confidence"))
    elif capability == "human.gesture":
        add(0, "gesture", result.get("gesture"), None, result.get("confidence"))
    elif capability in {"speech.diarize", "speech.align_transcript", "speech.meeting", "media.transcribe_video"}:
        for index, item in enumerate(result.get("segments") or []):
            if isinstance(item, dict):
                add(index, "timeline_segment", item, {"start": item.get("start"), "end": item.get("end")}, item.get("confidence"))
    elif capability in {"vision.embed", "vision.embed_text", "identity.face.embed"}:
        embedding = result.get("embedding")
        if isinstance(embedding, dict) and embedding.get("artifact"):
            add(0, "embedding", {"artifact": embedding.get("artifact"), "dimension": embedding.get("dimension"), "model": embedding.get("model")}, None, result.get("quality"))
    elif capability in {"identity.face.detect", "identity.face.verify", "vision.face_compare"}:
        if capability == "identity.face.detect":
            for index, item in enumerate(result.get("faces") or []):
                if isinstance(item, dict):
                    add(index, "face", item, {"bbox": item.get("bbox")}, item.get("confidence"))
        else:
            add(0, "face_verification", {"match": result.get("match"), "similarity": result.get("similarity"), "threshold": result.get("threshold"), "profile": result.get("profile")}, None, result.get("similarity"))
    elif capability in {"vision.geometry.distance", "vision.geometry.angle", "vision.geometry.area", "vision.geometry.contour", "vision.geometry.homography", "vision.geometry.match_features", "vision.geometry.perspective_transform", "vision.geometry.calibrate_camera", "vision.geometry.solve_pnp", "vision.transform.crop", "vision.transform.resize", "vision.transform.rotate", "vision.transform.warp", "vision.transform.colorspace", "vision.transform.blur", "vision.transform.threshold", "media.probe", "media.video.extract_frames", "media.video.trim", "media.video.transcode", "media.video.concat", "media.audio.extract", "media.audio.trim", "media.audio.resample", "media.audio.convert", "media.audio.normalize", "vision.human_state", "vision.measure"}:
        add(0, "operator_result", result, None, result.get("confidence"))
    return [item.to_dict() for item in records]


def aggregate_confidence(observations: list[dict[str, Any]]) -> float | None:
    values = [item.get("confidence") for item in observations if isinstance(item.get("confidence"), (int, float)) and not isinstance(item.get("confidence"), bool)]
    if not values:
        return None
    return round(sum(float(item) for item in values) / len(values), 6)


def evidence_from_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a de-duplicated evidence index for compact clients."""
    seen: set[str] = set()
    values: list[dict[str, Any]] = []
    for observation in observations:
        for item in observation.get("evidence") or []:
            key = json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if key not in seen:
                seen.add(key)
                values.append(item)
    return values
