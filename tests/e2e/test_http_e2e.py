from __future__ import annotations

import json
from pathlib import Path
import signal
import tempfile
import unittest

try:
    from .support import HttpService, http_request
except ImportError:
    from support import HttpService, http_request


class HttpE2ETests(unittest.TestCase):
    def test_health_readiness_capabilities_metrics_and_ocr(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "http.txt"
            source.write_text("HTTP E2E", encoding="utf-8")
            with HttpService(root / "home") as service:
                status, headers, body = http_request(f"{service.url}/health")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/json")
                self.assertEqual(json.loads(body)["status"], "ok")

                status, _, body = http_request(f"{service.url}/ready")
                self.assertEqual(status, 200)
                readiness = json.loads(body)
                self.assertIn(readiness["status"], {"ready", "degraded"})
                self.assertTrue(readiness["accepting_requests"])

                status, _, body = http_request(f"{service.url}/v1/capabilities")
                self.assertEqual(status, 200)
                capabilities = json.loads(body)["capabilities"]
                self.assertGreaterEqual(len(capabilities), 56)
                self.assertIn("media.probe", {item["capability"] for item in capabilities})

                status, _, body = http_request(f"{service.url}/v1/vision/ocr", method="POST", payload={"path": str(source)})
                self.assertEqual(status, 200)
                envelope = json.loads(body)
                self.assertEqual(envelope["result"]["blocks"][0]["text"], "HTTP E2E")
                self.assertIsNone(envelope["error"])

                status, headers, body = http_request(f"{service.url}/metrics")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "text/plain; version=0.0.4")
                metrics = body.decode("utf-8")
                self.assertIn("specialist_requests_total 1", metrics)
                self.assertIn("specialist_errors_total 0", metrics)

    def test_rejects_invalid_json_oversized_and_non_json_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            with HttpService(Path(temporary) / "home", max_request_bytes=32) as service:
                status, _, body = http_request(
                    f"{service.url}/v1/vision/ocr",
                    method="POST",
                    raw_body=b"{not valid json",
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)["error"]["code"], "invalid_json")

                status, _, body = http_request(
                    f"{service.url}/v1/vision/ocr",
                    method="POST",
                    raw_body=b"x" * 64,
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(status, 413)
                self.assertEqual(json.loads(body)["error"]["code"], "request_too_large")

                status, _, body = http_request(
                    f"{service.url}/v1/vision/ocr",
                    method="POST",
                    raw_body=b"{}",
                    headers={"Content-Type": "text/plain"},
                )
                self.assertEqual(status, 415)
                self.assertEqual(json.loads(body)["error"]["code"], "unsupported_media_type")

    def test_token_protection_and_graceful_sigterm(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with HttpService(root / "home", token="e2e-secret") as service:
                status, _, body = http_request(f"{service.url}/health")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["status"], "ok")

                status, _, body = http_request(f"{service.url}/v1/capabilities")
                self.assertEqual(status, 401)
                self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")

                status, _, body = http_request(
                    f"{service.url}/v1/capabilities",
                    headers={"Authorization": "Bearer e2e-secret"},
                )
                self.assertEqual(status, 200)
                self.assertGreaterEqual(len(json.loads(body)["capabilities"]), 56)

                process = service.process
                self.assertIsNotNone(process)
                process.send_signal(signal.SIGTERM)
                self.assertEqual(process.wait(timeout=5), 0)

    def test_ready_returns_503_when_a_capability_has_a_persisted_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            metadata = home / "metadata"
            metadata.mkdir(parents=True)
            (metadata / "vision__ocr.error.json").write_text(
                json.dumps({"capability": "vision.ocr", "status": "error", "message": "fixture failure"}),
                encoding="utf-8",
            )
            with HttpService(home) as service:
                status, _, body = http_request(f"{service.url}/ready")
                self.assertEqual(status, 503)
                readiness = json.loads(body)
                self.assertEqual(readiness["status"], "degraded")
                self.assertEqual(readiness["error_capabilities"], 1)
                self.assertFalse(readiness["accepting_requests"])


if __name__ == "__main__":
    unittest.main()
