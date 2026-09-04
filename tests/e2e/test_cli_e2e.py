from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

try:
    from .support import run_cli
except ImportError:  # unittest discover -s tests/e2e loads modules top-level
    from support import run_cli


class CliE2ETests(unittest.TestCase):
    def test_capabilities_doctor_and_fallback_ocr_use_real_cli_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            source = root / "note.txt"
            source.write_text("E2E hello", encoding="utf-8")

            capabilities = run_cli(["capabilities"], home)
            self.assertEqual(capabilities.returncode, 0, capabilities.stderr)
            capability_payload = json.loads(capabilities.stdout)
            self.assertEqual(len(capability_payload), 10)
            self.assertEqual({item["capability"] for item in capability_payload}, {
                "vision.detect",
                "vision.segment",
                "vision.ocr",
                "vision.depth",
                "screen.parse",
                "document.parse",
                "audio.transcribe",
                "audio.vad",
                "speech.synthesize",
                "speech.clone_voice",
            })

            ocr = run_cli(["--backend", "fallback", "ocr", str(source), "--json"], home)
            self.assertEqual(ocr.returncode, 0, ocr.stderr)
            envelope = json.loads(ocr.stdout)
            self.assertEqual(envelope["capability"], "vision.ocr")
            self.assertEqual(envelope["result"]["blocks"][0]["text"], "E2E hello")
            self.assertIsNone(envelope["error"])

            detect = run_cli(["--backend", "fallback", "detect", str(source), "--json"], home)
            self.assertEqual(detect.returncode, 0, detect.stderr)
            self.assertEqual(json.loads(detect.stdout)["capability"], "vision.detect")

            doctor = run_cli(["doctor", "--json"], home)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            doctor_payload = json.loads(doctor.stdout)
            self.assertEqual(len(doctor_payload["capabilities"]), 10)
            self.assertEqual(doctor_payload["home"], str(home))

            strict_doctor = run_cli(["--backend", "fallback", "doctor", "--strict", "--json"], home)
            self.assertEqual(strict_doctor.returncode, 1)
            strict_payload = json.loads(strict_doctor.stdout)
            self.assertTrue(any(item["status"] == "not installed" for item in strict_payload["capabilities"]))

    def test_invalid_input_returns_json_error_and_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            completed = run_cli(["ocr", str(Path(temporary) / "missing.txt"), "--json"], home)
            self.assertNotEqual(completed.returncode, 0)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["error"]["code"], "input_not_found")

    def test_strict_doctor_blocks_a_persisted_capability_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            metadata = home / "metadata"
            metadata.mkdir(parents=True)
            (metadata / "vision__ocr.error.json").write_text(
                json.dumps({"capability": "vision.ocr", "status": "error", "message": "fixture failure"}),
                encoding="utf-8",
            )
            completed = run_cli(["--backend", "fallback", "doctor", "--strict", "--json"], home)
            self.assertEqual(completed.returncode, 1)
            payload = json.loads(completed.stdout)
            ocr = next(item for item in payload["capabilities"] if item["capability"] == "vision.ocr")
            self.assertEqual(ocr["status"], "error")

    def test_install_models_list_and_remove_verify_local_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            artifact = root / "fixture-model.bin"
            artifact.write_bytes(b"specialist-e2e-artifact")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()

            install = run_cli([
                "install",
                "vision.ocr",
                "--source",
                artifact.as_uri(),
                "--sha256",
                digest,
            ], home)
            self.assertEqual(install.returncode, 0, install.stderr)
            install_payload = json.loads(install.stdout)
            self.assertEqual(install_payload[0]["capability"], "vision.ocr")
            self.assertEqual(install_payload[0]["artifact"]["sha256"], digest)
            installed_artifact = Path(install_payload[0]["artifact"]["path"])
            self.assertTrue(installed_artifact.is_file())

            models = run_cli(["models", "list"], home)
            self.assertEqual(models.returncode, 0, models.stderr)
            ocr_model = next(item for item in json.loads(models.stdout) if item["capability"] == "vision.ocr")
            self.assertEqual(ocr_model["status"], "ready")
            self.assertEqual(ocr_model["verification"]["status"], "verified")
            self.assertEqual(ocr_model["verification"]["sha256"], digest)

            remove = run_cli(["models", "remove", "vision.ocr"], home)
            self.assertEqual(remove.returncode, 0, remove.stderr)
            self.assertTrue(json.loads(remove.stdout)[0]["removed"])
            self.assertFalse(installed_artifact.exists())
            models_after = run_cli(["models", "list"], home)
            self.assertEqual(models_after.returncode, 0, models_after.stderr)
            removed_model = next(item for item in json.loads(models_after.stdout) if item["capability"] == "vision.ocr")
            self.assertEqual(removed_model["status"], "not installed")


if __name__ == "__main__":
    unittest.main()
