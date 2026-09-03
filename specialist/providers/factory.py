"""Select real providers when their optional dependencies are available."""

from __future__ import annotations

import importlib.util
import os
import shutil

from .builtin import BUILTIN_PROVIDERS
from .optional import CommandDocumentProvider, CommandScreenProvider, PaddleOCRProvider, SileroVADProvider, TransformersDepthProvider, UltralyticsSegmentProvider, WhisperCppProvider, YOLOProvider


def provider_map(backend="auto"):
    selected = dict(BUILTIN_PROVIDERS)
    if backend == "fallback":
        return selected
    candidates = {
        "vision.detect": ("ultralytics", YOLOProvider()),
        "vision.segment": ("ultralytics", UltralyticsSegmentProvider()),
        "vision.ocr": (("paddleocr", "paddle"), PaddleOCRProvider()),
        "vision.depth": (("transformers", "PIL", "torch"), TransformersDepthProvider()),
        "audio.transcribe": ("whisper-cli", WhisperCppProvider(binary=os.environ.get("SPECIALIST_WHISPER_BINARY", "whisper-cli"))),
        "audio.vad": ("silero_vad", SileroVADProvider()),
        "document.parse": ("mineru", CommandDocumentProvider(command=os.environ.get("SPECIALIST_MINERU_COMMAND", "mineru"))),
        "screen.parse": ("omniparser", CommandScreenProvider(command=os.environ.get("SPECIALIST_OMNIPARSER_COMMAND", "omniparser"))),
    }
    for capability, (dependencies, provider) in candidates.items():
        if isinstance(dependencies, str):
            dependencies = (dependencies,)
        available = all(importlib.util.find_spec(dependency) is not None for dependency in dependencies)
        command_dependencies = {"whisper-cli", "magic-pdf", "mineru", "omniparser"}
        if any(dependency in command_dependencies for dependency in dependencies):
            # Command providers are selected automatically only after the
            # runtime has a verified artifact marker. Without that state a
            # host-installed binary would make fresh fallback calls fail
            # closed unexpectedly (and could imply an unpinned model).
            available = backend == "real" and all(shutil.which(dependency) is not None for dependency in dependencies if dependency in command_dependencies)
        if backend == "real" or available:
            selected[capability] = provider
    return selected
