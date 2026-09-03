from __future__ import annotations

import json
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest

try:
    from .support import HttpService, ROOT, run_cli, test_environment
except ImportError:
    from support import HttpService, ROOT, run_cli, test_environment


class WorkerE2ETests(unittest.TestCase):
    def test_isolated_cli_request_crosses_worker_process_and_writes_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            source = root / "worker.txt"
            source.write_text("worker boundary", encoding="utf-8")
            completed = run_cli(["--isolate", "ocr", str(source), "--json"], home)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            envelope = json.loads(completed.stdout)
            self.assertEqual(envelope["capability"], "vision.ocr")
            self.assertEqual(envelope["result"]["blocks"][0]["text"], "worker boundary")
            self.assertFalse(envelope["performance"]["cached"])
            worker_log = home / "logs" / "vision__ocr.worker.log"
            self.assertTrue(worker_log.is_file(), f"missing worker log under {home}")

    def test_persistent_worker_is_reused_for_uncached_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "reuse.txt"
            source.write_text("warm worker", encoding="utf-8")
            with HttpService(root / "home") as service:
                first_status, _, first_body = self._post(service.url, source, 1)
                second_status, _, second_body = self._post(service.url, source, 2)
                self.assertEqual(first_status, 200)
                self.assertEqual(second_status, 200)
                first = json.loads(first_body)
                second = json.loads(second_body)
                self.assertTrue(first["performance"]["cold_start"])
                self.assertFalse(second["performance"]["cold_start"])
                self.assertFalse(second["performance"]["cached"])
                process = service.process
                self.assertIsNotNone(process)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 0)

    @staticmethod
    def _post(base_url: str, source: Path, marker: int):
        try:
            from .support import http_request
        except ImportError:
            from support import http_request

        return http_request(
            f"{base_url}/v1/vision/ocr",
            method="POST",
            payload={"path": str(source), "options": {"e2e_marker": marker}},
        )

    def test_worker_protocol_returns_error_json_for_malformed_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            process = subprocess.run(
                [
                    __import__("sys").executable,
                    "-m",
                    "specialist",
                    "--home",
                    str(home),
                    "_worker",
                    "--capability",
                    "vision.ocr",
                ],
                cwd=ROOT,
                env=test_environment(home),
                input="{malformed json}\n",
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
            self.assertEqual(response["error"]["code"], "worker_protocol_error")


if __name__ == "__main__":
    unittest.main()
