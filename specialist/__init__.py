"""Public Python SDK for Specialist Runtime."""

from .runtime import SpecialistRuntime


class Specialist:
    """Small, synchronous SDK facade over the local runtime.

    The facade intentionally mirrors the capability names in the CLI while
    keeping the underlying provider implementation private and replaceable.
    """

    def __init__(self, home=None, provider_overrides=None, **runtime_options):
        self.runtime = SpecialistRuntime(home=home, provider_overrides=provider_overrides, **runtime_options)

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


__all__ = ["Specialist", "SpecialistRuntime"]
__version__ = "1.0.1"
