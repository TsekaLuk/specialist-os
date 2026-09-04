"""First-party capability packs for discoverable installation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .registry import BUNDLES


@dataclass(frozen=True)
class CapabilityPack:
    name: str
    description: str
    capabilities: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "capabilities": list(self.capabilities)}


PACKS = (
    CapabilityPack("vision-core", "Detection, segmentation, OCR and depth", ("vision.detect", "vision.segment", "vision.ocr", "vision.depth")),
    CapabilityPack("document", "Document parsing and structure recovery", ("document.parse",)),
    CapabilityPack("voice", "Speech synthesis, voice cloning, transcription and activity detection", ("speech.synthesize", "speech.clone_voice", "audio.transcribe", "audio.vad")),
    CapabilityPack("screen", "Actionable screen element parsing", ("screen.parse",)),
    CapabilityPack("spatial", "Depth and geometry primitives", ("vision.depth", "vision.detect", "vision.segment")),
    CapabilityPack("human", "Pose, hand, face landmarks and gestures", tuple(BUNDLES.get("human", ()))),
    CapabilityPack("identity", "Local sensitive face detection, embeddings and verification", tuple(BUNDLES.get("identity", ()))),
    CapabilityPack("audio-plus", "Diarization, denoising and meeting timelines", tuple(BUNDLES.get("audio-plus", ()))),
    CapabilityPack("retrieval", "Image and text embeddings with semantic search", tuple(BUNDLES.get("retrieval", ()))),
    CapabilityPack("media", "Deterministic FFmpeg media operations", tuple(BUNDLES.get("media", ()))),
    CapabilityPack("vision-operators", "Geometry, transforms and measurement operators", tuple(BUNDLES.get("vision-operators", ()))),
    CapabilityPack("core", "Complete Specialist capability surface with lazy providers", tuple(BUNDLES.get("core", ()))),
)

_PACK_ALIASES = {
    "vision": "vision-core",
    "audio": "voice",
    "all": "core",
}


def get_pack(name: str) -> CapabilityPack:
    key = _PACK_ALIASES.get(name.strip().lower(), name.strip().lower())
    for pack in PACKS:
        if pack.name == key:
            return pack
    raise KeyError(f"unknown capability pack '{name}'")
