import json
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
        self.assertEqual(len(json.loads(completed.stdout)), 8)

    def test_json_error_has_nonzero_exit(self):
        completed = subprocess.run([sys.executable, "-m", "specialist", "ocr", "/tmp/does-not-exist", "--json"], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(json.loads(completed.stdout)["error"]["code"], "input_not_found")


if __name__ == "__main__":
    unittest.main()
