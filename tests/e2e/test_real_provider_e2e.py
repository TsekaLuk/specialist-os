"""Opt-in integration tests for real model providers.

These tests are intentionally excluded from the dependency-free CI path. Set
SPECIALIST_RUN_REAL_PROVIDER_E2E=1 after installing the provider packages to
exercise pinned registry artifacts and normalized result schemas.
"""

from __future__ import annotations

import os
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from specialist.runtime import SpecialistRuntime


RUN_REAL = os.environ.get("SPECIALIST_RUN_REAL_PROVIDER_E2E") == "1"


@unittest.skipUnless(RUN_REAL, "set SPECIALIST_RUN_REAL_PROVIDER_E2E=1 to run real provider integration tests")
class RealProviderE2ETests(unittest.TestCase):
    def _enabled(self, provider: str) -> bool:
        selected = {item.strip() for item in os.environ.get("SPECIALIST_REAL_PROVIDERS", "yolo").split(",") if item.strip()}
        if provider not in selected:
            self.skipTest(f"provider {provider} is not selected in SPECIALIST_REAL_PROVIDERS")
        return True

    def _image_fixture(self, root: Path) -> Path:
        fixture = Path(os.environ.get("SPECIALIST_REAL_IMAGE", "tests/assets/sample.ppm"))
        self.assertTrue(fixture.is_file(), fixture)
        from PIL import Image

        image = Image.open(fixture)
        target = root / "sample.png"
        image.save(target, format="PNG")
        return target

    def _audio_fixture(self, root: Path) -> Path:
        target = root / "sample.wav"
        with wave.open(str(target), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            # A deterministic low-level tone exercises the full PCM path
            # without committing a binary voice recording to the repository.
            frames = b"".join(struct.pack("<h", 5000 if (index // 80) % 2 else -5000) for index in range(16000))
            stream.writeframes(frames)
        return target

    def test_yolo_pinned_artifact_produces_valid_detection_schema(self):
        self._enabled("yolo")
        with tempfile.TemporaryDirectory() as temp:
            fixture = self._image_fixture(Path(temp))
            runtime = SpecialistRuntime(home=Path(temp) / "home", backend="real", isolate=True)
            try:
                runtime.install("vision.detect", with_dependencies=False)
                result = runtime.run("vision.detect", fixture, {"device": "cpu"})
                self.assertIsNone(result["error"], result)
                self.assertIsInstance(result["result"]["items"], list)
            finally:
                runtime.close()

    def test_sam_pinned_artifact_produces_prompted_mask(self):
        self._enabled("sam")
        with tempfile.TemporaryDirectory() as temp:
            fixture = self._image_fixture(Path(temp))
            runtime = SpecialistRuntime(home=Path(temp) / "home", backend="real", isolate=True)
            try:
                runtime.install("vision.segment", with_dependencies=False)
                result = runtime.run("vision.segment", fixture, {"point": [320, 240], "device": "cpu"})
                self.assertIsNone(result["error"], result)
                self.assertIsInstance(result["result"]["masks"], list)
                self.assertGreaterEqual(len(result["result"]["masks"]), 1)
            finally:
                runtime.close()

    def test_paddleocr_pinned_bundle_produces_text_blocks(self):
        self._enabled("paddleocr")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self._image_fixture(root)
            runtime = SpecialistRuntime(home=root / "home", backend="real", isolate=True)
            try:
                runtime.install("vision.ocr", with_dependencies=False)
                result = runtime.run("vision.ocr", fixture, {"device": "cpu"})
                self.assertIsNone(result["error"], result)
                self.assertIsInstance(result["result"]["blocks"], list)
            finally:
                runtime.close()

    def test_silero_pinned_artifact_returns_audio_intervals(self):
        self._enabled("silero")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self._audio_fixture(root)
            runtime = SpecialistRuntime(home=root / "home", backend="real", isolate=True)
            try:
                runtime.install("audio.vad", with_dependencies=False)
                result = runtime.run("audio.vad", fixture, {"device": "cpu"})
                self.assertIsNone(result["error"], result)
                self.assertAlmostEqual(result["result"]["duration_seconds"], 1.0, places=2)
                self.assertIsInstance(result["result"]["segments"], list)
            finally:
                runtime.close()

    def test_whisper_cpp_pinned_model_returns_transcription_schema(self):
        self._enabled("whisper")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = self._audio_fixture(root)
            runtime = SpecialistRuntime(home=root / "home", backend="real", isolate=True)
            try:
                runtime.install("audio.transcribe", with_dependencies=False)
                result = runtime.run("audio.transcribe", fixture, {"device": "cpu"})
                self.assertIsNone(result["error"], result)
                self.assertIsInstance(result["result"]["text"], str)
                self.assertIsInstance(result["result"]["segments"], list)
            finally:
                runtime.close()

    def test_depth_pinned_bundle_is_loaded_without_network_downloads(self):
        self._enabled("depth")
        if os.environ.get("SPECIALIST_RUN_HEAVY_REAL", "").strip().lower() not in {"1", "true", "yes", "on"}:
            self.skipTest("set SPECIALIST_RUN_HEAVY_REAL=1 on a host with at least 2 GiB available for Depth Anything")
        with tempfile.TemporaryDirectory() as temp:
            fixture = self._image_fixture(Path(temp))
            runtime = SpecialistRuntime(home=Path(temp) / "home", backend="real", isolate=True)
            try:
                runtime.install("vision.depth", with_dependencies=False)
                result = runtime.run("vision.depth", fixture, {"device": "cpu"})
                self.assertIsNone(result["error"], result)
                self.assertGreater(result["result"]["width"], 0)
                self.assertGreater(result["result"]["height"], 0)
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
