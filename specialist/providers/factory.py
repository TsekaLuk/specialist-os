"""Select real providers when their optional dependencies are available."""

from __future__ import annotations

import importlib.util
import os
import shutil

from .builtin import BUILTIN_PROVIDERS
from .expansion import EXPANSION_PROVIDERS
from .optional_expansion import OPTIONAL_EXPANSION_PROVIDERS
from .optional import CommandDocumentProvider, OmniParserProvider, PaddleOCRProvider, SileroVADProvider, TransformersDepthProvider, UltralyticsSegmentProvider, WhisperCppProvider, YOLOProvider
from .fish_audio import FishAudioProvider, SystemTTSProvider


def _module_available(module: str) -> bool:
    """Probe an optional module without letting a missing parent package escape."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def provider_map(backend="auto"):
    selected = dict(BUILTIN_PROVIDERS)
    selected.update(EXPANSION_PROVIDERS)
    if backend == "fallback":
        selected["speech.synthesize"] = FishAudioProvider("speech.synthesize")
        selected["speech.clone_voice"] = FishAudioProvider("speech.clone_voice")
        selected["speech.synthesize@system_tts"] = SystemTTSProvider()
        return selected
    candidates = {
        "vision.detect": ("ultralytics", YOLOProvider()),
        "vision.segment": ("ultralytics", UltralyticsSegmentProvider()),
        "vision.ocr": (("paddleocr", "paddle"), PaddleOCRProvider()),
        "vision.depth": (("transformers", "PIL", "torch"), TransformersDepthProvider()),
        "audio.transcribe": ("whisper-cli", WhisperCppProvider(binary=os.environ.get("SPECIALIST_WHISPER_BINARY", "whisper-cli"))),
        "audio.vad": ("silero_vad", SileroVADProvider()),
        "document.parse": ("mineru", CommandDocumentProvider(command=os.environ.get("SPECIALIST_MINERU_COMMAND", "mineru"))),
        "screen.parse": (("ultralytics", "transformers", "torch", "torchvision", "paddleocr", "paddle", "PIL"), OmniParserProvider()),
        # The adapter is HTTP-only and has no Fish/PyTorch import. The system
        # TTS provider is a genuine local fallback when the OS offers one.
        "speech.synthesize": (None, FishAudioProvider("speech.synthesize")),
        "speech.clone_voice": (None, FishAudioProvider("speech.clone_voice")),
    }
    # Expansion providers keep heavy imports lazy. The dependency probe only
    # checks the top-level package; model loading happens at first use.
    expansion_candidates = {
        "human.pose": ("mediapipe", OPTIONAL_EXPANSION_PROVIDERS["human.pose"]),
        "human.hand_landmarks": ("mediapipe", OPTIONAL_EXPANSION_PROVIDERS["human.hand_landmarks"]),
        "human.face_landmarks": ("mediapipe", OPTIONAL_EXPANSION_PROVIDERS["human.face_landmarks"]),
        "human.gesture": ("mediapipe", OPTIONAL_EXPANSION_PROVIDERS["human.gesture"]),
        "speech.diarize": ("pyannote.audio", OPTIONAL_EXPANSION_PROVIDERS["speech.diarize"]),
        "audio.denoise": ("df", OPTIONAL_EXPANSION_PROVIDERS["audio.denoise"]),
        "vision.embed": ("open_clip", OPTIONAL_EXPANSION_PROVIDERS["vision.embed"]),
        "vision.embed_text": ("open_clip", OPTIONAL_EXPANSION_PROVIDERS["vision.embed_text"]),
        "vision.similarity": ("open_clip", OPTIONAL_EXPANSION_PROVIDERS["vision.similarity"]),
        "vision.search": ("open_clip", OPTIONAL_EXPANSION_PROVIDERS["vision.search"]),
        "identity.face.detect": ("insightface", OPTIONAL_EXPANSION_PROVIDERS["identity.face.detect"]),
        "identity.face.embed": ("insightface", OPTIONAL_EXPANSION_PROVIDERS["identity.face.embed"]),
        "identity.face.verify": ("insightface", OPTIONAL_EXPANSION_PROVIDERS["identity.face.verify"]),
    }
    candidates.update(expansion_candidates)
    for capability, (dependencies, provider) in candidates.items():
        if dependencies is None:
            selected[capability] = provider
            continue
        if isinstance(dependencies, str):
            dependencies = (dependencies,)
        available = all(_module_available(dependency) for dependency in dependencies)
        command_dependencies = {"whisper-cli", "magic-pdf", "mineru"}
        if any(dependency in command_dependencies for dependency in dependencies):
            # Command providers are selected automatically only after the
            # runtime has a verified artifact marker. Without that state a
            # host-installed binary would make fresh fallback calls fail
            # closed unexpectedly (and could imply an unpinned model).
            available = backend == "real" and all(shutil.which(dependency) is not None for dependency in dependencies if dependency in command_dependencies)
        if backend == "real" or available:
            selected[capability] = provider
    selected["speech.synthesize@system_tts"] = SystemTTSProvider()
    return selected
