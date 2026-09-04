"""Public Python SDK for Specialist Runtime."""

import tempfile
from pathlib import Path

from .runtime import SpecialistRuntime
from .graph import SpecialistGraph
from .cascade import SpecialistCascade
from .node import ComputeNode, NodeScheduler
from .provider_sdk import ProviderAdapter, ProviderResult


class SpeechFacade:
    def __init__(self, specialist):
        self._specialist = specialist

    def synthesize(self, text, *, voice=None, language=None, style=None, format="wav", profile="balanced", provider=None, stream=False, **options):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        temporary = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
        try:
            temporary.write(text)
            temporary.close()
            request = {**options, "text": text, "format": format, "profile": profile, "stream": stream}
            if voice is not None:
                request["voice"] = voice
            if language is not None:
                request["language"] = language
            if style is not None:
                request["style"] = style if isinstance(style, dict) else {"instruction": style}
            if provider is not None:
                request["provider"] = provider
            return self._specialist.run("speech.synthesize", temporary.name, request)
        finally:
            Path(temporary.name).unlink(missing_ok=True)

    def clone_voice(self, text, reference_audio, *, reference_text=None, style=None, format="wav", provider="fish_audio", **options):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        reference = Path(reference_audio).expanduser()
        request = {**options, "text": text, "reference_audio": str(reference), "format": format, "provider": provider}
        if reference_text is not None:
            request["reference_text"] = reference_text
        if style is not None:
            request["style"] = style if isinstance(style, dict) else {"instruction": style}
        return self._specialist.run("speech.clone_voice", reference, request)


class Specialist:
    """Small, synchronous SDK facade over the local runtime.

    The facade intentionally mirrors the capability names in the CLI while
    keeping the underlying provider implementation private and replaceable.
    """

    def __init__(self, home=None, provider_overrides=None, **runtime_options):
        self.runtime = SpecialistRuntime(home=home, provider_overrides=provider_overrides, **runtime_options)
        self.speech = SpeechFacade(self)

    def run(self, capability, input_path, options=None):
        return self.runtime.run(capability, input_path, options or {})

    def detect(self, input_path, **options):
        return self.run("vision.detect", input_path, options)

    def segment(self, input_path, prompt=None, **options):
        if prompt is not None:
            options["prompt"] = prompt
        return self.run("vision.segment", input_path, options)

    def ocr(self, input_path, **options):
        return self.run("vision.ocr", input_path, options)

    def depth(self, input_path, **options):
        return self.run("vision.depth", input_path, options)

    def parse_screen(self, input_path, **options):
        return self.run("screen.parse", input_path, options)

    def parse_document(self, input_path, **options):
        return self.run("document.parse", input_path, options)

    def transcribe(self, input_path, **options):
        return self.run("audio.transcribe", input_path, options)

    def vad(self, input_path, **options):
        return self.run("audio.vad", input_path, options)

    def speak(self, text, **options):
        return self.speech.synthesize(text, **options)

    def clone_voice(self, text, reference_audio, **options):
        return self.speech.clone_voice(text, reference_audio, **options)

    def graph(self, name="specialist-graph"):
        return SpecialistGraph(name)

    def cascade(self, name="specialist-cascade"):
        return SpecialistCascade(name=name)

    def open_session(self, capability, **options):
        return self.runtime.open_session(capability, options)


__all__ = ["Specialist", "SpeechFacade", "SpecialistRuntime", "SpecialistGraph", "SpecialistCascade", "ComputeNode", "NodeScheduler", "ProviderAdapter", "ProviderResult"]
__version__ = "1.0.4"
