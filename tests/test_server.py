import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from specialist.runtime import SpecialistRuntime
from specialist.server import RuntimeRequestHandler


class ServerTests(unittest.TestCase):
    def test_token_protects_capability_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = SpecialistRuntime(home=Path(temp) / "home")
            handler = type("Handler", (RuntimeRequestHandler,), {"runtime": runtime})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.api_token = "secret"
            server.max_request_bytes = 1024
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/v1/capabilities"
            try:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(url, timeout=2)
                self.assertEqual(caught.exception.code, 401)
                caught.exception.close()
                request = urllib.request.Request(url, headers={"Authorization": "Bearer secret"})
                with urllib.request.urlopen(request, timeout=2) as response:
                    capabilities = json.loads(response.read())["capabilities"]
                    self.assertGreaterEqual(len(capabilities), 56)
                    self.assertIn("vision.measure", {item["capability"] for item in capabilities})
                metrics_request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/metrics", headers={"Authorization": "Bearer secret"})
                with urllib.request.urlopen(metrics_request, timeout=2) as response:
                    self.assertIn("specialist_requests_total", response.read().decode())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
