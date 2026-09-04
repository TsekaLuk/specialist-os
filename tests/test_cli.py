import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_json_command(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            source = Path(temp) / "message.txt"
            source.write_text("hello", encoding="utf-8")
            command = [sys.executable, "-m", "specialist", "--home", str(home), "ocr", str(source), "--json"]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["capability"], "vision.ocr")
            self.assertEqual(payload["result"]["blocks"][0]["text"], "hello")

    def test_capabilities(self):
        completed = subprocess.run([sys.executable, "-m", "specialist", "capabilities"], cwd=ROOT, capture_output=True, text=True, check=True)
        payload = json.loads(completed.stdout)
        self.assertGreaterEqual(len(payload), 56)
        names = {item["capability"] for item in payload}
        self.assertIn("vision.geometry.distance", names)
        self.assertIn("media.video.extract_frames", names)

    def test_json_error_has_nonzero_exit(self):
        completed = subprocess.run([sys.executable, "-m", "specialist", "ocr", "/tmp/does-not-exist", "--json"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "input_not_found")

    def test_provider_lifecycle_accepts_provider_name_and_reports_clean_error(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            environment = os.environ.copy()
            environment["SPECIALIST_FISH_AUDIO_URL"] = f"http://127.0.0.1:{port}"
            environment["SPECIALIST_FISH_AUDIO_START_POLICY"] = "manual"
            completed = subprocess.run(
                [sys.executable, "-m", "specialist", "--home", str(home), "provider", "start", "fish_audio"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
