"""Frozen ADR-003 product families, independent of future provider registration."""

from types import MappingProxyType
from typing import Iterable


CORE_FAMILIES = MappingProxyType({
    "detection": ("vision.detect",),
    "segmentation": ("vision.segment",),
    "ocr": ("vision.ocr",),
    "depth": ("vision.depth",),
    "screen": ("screen.parse",),
    "document": ("document.parse",),
    "speech_recognition": ("audio.transcribe", "audio.vad"),
    "diarization": ("speech.diarize", "speech.align_transcript", "speech.meeting"),
    "denoise": ("audio.denoise",),
    "speech_generation": ("speech.synthesize", "speech.clone_voice"),
    "human_landmarks": ("human.pose", "human.hand_landmarks", "human.face_landmarks", "human.gesture", "vision.human_state"),
    "visual_search": ("vision.embed", "vision.embed_text", "vision.similarity", "vision.search", "vision.find_similar"),
    "face_identity": ("identity.face.detect", "identity.face.embed", "identity.face.verify", "vision.face_compare"),
    "geometry": (
        "vision.geometry.distance", "vision.geometry.angle", "vision.geometry.area",
        "vision.geometry.contour", "vision.geometry.homography", "vision.geometry.match_features",
        "vision.geometry.perspective_transform", "vision.geometry.calibrate_camera",
        "vision.geometry.solve_pnp", "vision.transform.crop", "vision.transform.resize",
        "vision.transform.rotate", "vision.transform.warp", "vision.transform.colorspace",
        "vision.transform.blur", "vision.transform.threshold", "vision.measure",
    ),
    "media": (
        "media.probe", "media.video.extract_frames", "media.video.trim",
        "media.video.transcode", "media.video.concat", "media.audio.extract",
        "media.audio.trim", "media.audio.resample", "media.audio.convert",
        "media.audio.normalize", "media.transcribe_video",
    ),
})

CORE_CAPABILITIES = frozenset(name for names in CORE_FAMILIES.values() for name in names)
CORE_FAMILY_BY_CAPABILITY = MappingProxyType({
    name: family for family, names in CORE_FAMILIES.items() for name in names
})


def core_install_targets(registered_names: Iterable[str]) -> list[str]:
    """Keep registry order without implicitly admitting newly registered APIs."""
    return [name for name in registered_names if name in CORE_CAPABILITIES]
