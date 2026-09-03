"""First-party capability packs for discoverable installation workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
    CapabilityPack("voice", "Speech transcription and activity detection", ("audio.transcribe", "audio.vad")),
    CapabilityPack("screen", "Actionable screen element parsing", ("screen.parse",)),
    CapabilityPack("spatial", "Depth and geometry primitives", ("vision.depth", "vision.detect", "vision.segment")),
)


def get_pack(name: str) -> CapabilityPack:
    key = name.strip().lower()
    for pack in PACKS:
        if pack.name == key:
            return pack
    raise KeyError(f"unknown capability pack '{name}'")
