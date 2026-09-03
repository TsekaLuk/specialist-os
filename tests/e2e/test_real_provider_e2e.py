"""Opt-in integration tests for real model providers.

These tests are intentionally excluded from the dependency-free CI path. Set
SPECIALIST_RUN_REAL_PROVIDER_E2E=1 after installing the provider packages to
exercise pinned registry artifacts and normalized result schemas.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from specialist.runtime import SpecialistRuntime


RUN_REAL = os.environ.get("SPECIALIST_RUN_REAL_PROVIDER_E2E") == "1"


@unittest.skipUnless(RUN_REAL, "set SPECIALIST_RUN_REAL_PROVIDER_E2E=1 to run real provider integration tests")
class RealProviderE2ETests(unittest.TestCase):
    def _image_fixture(self, root: Path) -> Path:
        fixture = Path(os.environ.get("SPECIALIST_REAL_IMAGE", "tests/assets/sample.ppm"))
        self.assertTrue(fixture.is_file(), fixture)
        from PIL import Image

        image = Image.open(fixture)
        target = root / "sample.png"
        image.save(target, format="PNG")
        return target

    def test_yolo_pinned_artifact_produces_valid_detection_schema(self):
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

    def test_depth_pinned_bundle_is_loaded_without_network_downloads(self):
        if os.environ.get("SPECIALIST_RUN_HEAVY_REAL") != "1":
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
