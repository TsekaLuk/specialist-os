import json
import hashlib
import math
import tempfile
import unittest
from pathlib import Path

from specialist import Specialist
from specialist.runtime import SpecialistRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"
        self.input = Path(self.temp.name) / "note.txt"
        self.input.write_text("保存", encoding="utf-8")
        self.runtime = SpecialistRuntime(home=self.home)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_capabilities_share_envelope(self):
        for capability in ["detect", "segment", "ocr", "depth", "parse-screen", "parse-document", "transcribe", "vad"]:
            value = self.runtime.run(capability, self.input)
            self.assertIn("capability", value)
            self.assertIn("provider", value)
            self.assertIn("model", value)
            self.assertIn("input", value)
            self.assertIn("result", value)
            self.assertIn("performance", value)
            self.assertIsNone(value["error"])

    def test_ocr_text_fallback_and_cache(self):
        first = self.runtime.run("ocr", self.input)
        self.assertEqual(first["result"]["blocks"][0]["text"], "保存")
        second = self.runtime.run("vision.ocr", self.input)
        self.assertTrue(second["performance"]["cached"])
        events = (self.home / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(json.loads(events[-1])["event"], "capability.run")

    def test_provider_lifecycle_reports_warm_start(self):
        first = self.runtime.run("ocr", self.input, {"variant": "first"})
        second = self.runtime.run("ocr", self.input, {"variant": "second"})
        self.assertTrue(first["performance"]["cold_start"])
        self.assertFalse(second["performance"]["cold_start"])

    def test_cache_clean_keeps_pinned_capability_results(self):
        self.runtime.run("ocr", self.input, {"cache": 1})
        self.runtime.pin_model("vision.ocr")
        self.runtime.run("ocr", self.input, {"cache": 2})
        self.assertEqual(self.runtime.clean_cache(max_entries=0)["removed_results"], 0)

    def test_missing_file_is_structured_error(self):
        value = self.runtime.run("ocr", self.home / "missing.png")
        self.assertEqual(value["error"]["code"], "input_not_found")

    def test_invalid_request_is_structured_error(self):
        self.assertEqual(self.runtime.run("ocr", self.input, ["bad"])["error"]["code"], "invalid_options")
        self.assertEqual(self.runtime.run("ocr", None)["error"]["code"], "invalid_input")
        self.assertEqual(self.runtime.run("ocr", self.input, {"timeout_seconds": 999})["error"]["code"], "invalid_options")
        self.assertEqual(self.runtime.run("ocr", self.input, {"score": math.nan})["error"]["code"], "invalid_options")

    def test_install_and_doctor(self):
        self.runtime.install("vision")
        statuses = {item["capability"]: item["status"] for item in self.runtime.doctor()["capabilities"]}
        self.assertEqual(statuses["vision.ocr"], "ready")
        self.assertEqual(statuses["audio.vad"], "not installed")
        metadata = self.runtime.cache.installation("vision.ocr")
        self.assertIn("download_date", metadata)
        self.assertIn("license", metadata)
        self.assertIn("commercial", metadata)

    def test_sdk(self):
        result = Specialist(home=self.home).ocr(self.input)
        self.assertEqual(result["capability"], "vision.ocr")

    def test_pin_auto_installs_marker(self):
        self.assertEqual(self.runtime.pin_model("vision.ocr")[0]["pinned"], True)
        self.assertTrue(self.runtime.cache.installation("vision.ocr")["pinned"])

    def test_artifact_install_is_atomic_and_verified(self):
        artifact = self.home.parent / "model.bin"
        artifact.write_bytes(b"model-data")
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        installed = self.runtime.install("vision.ocr", source=artifact.as_uri(), sha256=checksum)
        self.assertEqual(installed[0]["artifact"]["sha256"], checksum)
        self.assertEqual(self.runtime.cache.installation("vision.ocr")["sha256"], checksum)
        artifact_path = Path(self.runtime.cache.installation("vision.ocr")["artifact_path"])
        self.assertTrue(artifact_path.exists())
        self.runtime.remove_model("vision.ocr")
        self.assertFalse(artifact_path.exists())

    def test_artifact_checksum_failure_leaves_no_installation(self):
        artifact = self.home.parent / "bad-model.bin"
        artifact.write_bytes(b"model-data")
        with self.assertRaises(Exception):
            self.runtime.install("vision.ocr", source=artifact.as_uri(), sha256="0" * 64)
        self.assertIsNone(self.runtime.cache.installation("vision.ocr"))

    def test_existing_model_marker_controls_result_identity(self):
        self.runtime.cache.mark_installed("vision.detect", "yolo", "yolo11n", status="ready")
        result = self.runtime.run("vision.detect", self.input)
        self.assertEqual(result["model"], "yolo11n")
        self.assertEqual(result["provider"], "yolo")

    def test_remote_artifacts_require_checksum(self):
        with self.assertRaises(ValueError):
            self.runtime.install("vision.ocr", source="https://example.invalid/model.bin")

    def test_provider_environment_starts_uninstalled(self):
        state = self.runtime.environments.status("paddleocr")
        self.assertEqual(state["status"], "not installed")

    def test_readiness_reports_provider_failures_instead_of_always_ready(self):
        class UnreadyProvider:
            name = "test-provider"
            requires_verified_artifact = False

            def doctor(self, _hardware):
                return {"status": "not ready", "error": {"code": "fixture_unavailable", "message": "fixture provider is unavailable"}}

        runtime = SpecialistRuntime(home=self.home / "readiness", backend="fallback", provider_overrides={"vision.ocr": UnreadyProvider()})
        readiness = runtime.readiness()
        self.assertEqual(readiness["status"], "degraded")
        self.assertGreater(readiness["ready_capabilities"], 0)
        self.assertGreaterEqual(readiness["unready_capabilities"], 1)
        self.assertEqual(readiness["ready_capabilities"] + readiness["unready_capabilities"], readiness["capabilities"])
        self.assertTrue(readiness["accepting_requests"])
        ocr = next(item for item in readiness["details"] if item["capability"] == "vision.ocr")
        self.assertEqual(ocr["status"], "unavailable")
        self.assertIn("fixture provider", ocr["reason"])

    def test_lru_unloads_unpinned_provider(self):
        runtime = SpecialistRuntime(home=self.home / "lru", max_loaded=1)
        runtime.run("ocr", self.input, {"lru": 1})
        runtime.run("detect", self.input, {"lru": 2})
        self.assertEqual(runtime._loaded, {"vision.detect"})


if __name__ == "__main__":
    unittest.main()
