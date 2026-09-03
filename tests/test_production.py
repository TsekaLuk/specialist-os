import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from specialist.cache import Cache
from specialist.environments import ProviderEnvironmentManager
from specialist.registry import CAPABILITIES, REGISTRY_DOCUMENT
from specialist.runtime import SpecialistRuntime
from specialist.server import RuntimeRequestHandler
from specialist.providers.optional import OptionalProvider


class ProductionBoundaryTests(unittest.TestCase):
    def test_optional_provider_is_fail_closed_without_verified_artifact(self):
        class FakeProvider(OptionalProvider):
            def __init__(self):
                super().__init__("fake", "vision.ocr", "fake-model")

            def _check_dependency(self):
                return None

            def _load_model(self):
                return None

            def infer(self, input_path, options, cache):
                self.load()
                return {"blocks": []}, []

        with tempfile.TemporaryDirectory() as temp:
            cache = Cache(Path(temp) / "home")
            provider = FakeProvider()
            provider._cache = cache
            provider._allow_unverified_models = False
            with self.assertRaises(Exception) as caught:
                provider.infer(Path(temp) / "input", {}, cache)
            self.assertEqual(caught.exception.code, "model_artifact_required")

    def test_invalid_provider_result_is_rejected_at_runtime_boundary(self):
        class BadProvider:
            name = "bad"
            model = "bad-model"
            supported_devices = ("cpu",)

            def install(self, cache, spec):
                cache.mark_installed(spec.name, self.name, self.model)
                return {}

            def doctor(self, _hardware):
                return {"status": "ready"}

            def load(self):
                return self

            def unload(self):
                return None

            def infer(self, _input_path, _options, _cache):
                return {"not_blocks": []}, []

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.txt"
            source.write_text("bad", encoding="utf-8")
            result = SpecialistRuntime(home=root / "home", provider_overrides={"vision.ocr": BadProvider()}).run("ocr", source)
            self.assertEqual(result["error"]["code"], "invalid_provider_result")

    def test_registry_is_validated_and_has_one_recommended_model(self):
        self.assertEqual(REGISTRY_DOCUMENT["schema_version"], 1)
        self.assertEqual(len(CAPABILITIES), 8)
        for spec in CAPABILITIES.values():
            self.assertEqual(sum(item.recommended for item in spec.models), 1)
            self.assertEqual(spec.model_spec().id, spec.model)

    def test_deepseek_harness_lists_every_core_tool(self):
        tools = json.loads((Path(__file__).parents[1] / "integrations" / "deepseek_harness" / "tools.json").read_text(encoding="utf-8"))["tools"]
        self.assertEqual({item["capability"] for item in tools}, set(CAPABILITIES))

    def test_environment_manager_creates_reusable_isolated_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = ProviderEnvironmentManager(Cache(Path(temp) / "home"), timeout_seconds=120)
            first = manager.ensure("test-provider", requirements=[])
            second = manager.ensure("test-provider", requirements=[])
            self.assertEqual(first["status"], "ready")
            self.assertEqual(second["status"], "ready")
            self.assertTrue(manager.verify("test-provider", []))

    def test_corrupt_artifact_is_reported_by_models_and_doctor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "model.bin"
            source.write_bytes(b"verified")
            checksum = hashlib.sha256(source.read_bytes()).hexdigest()
            runtime = SpecialistRuntime(home=root / "home")
            runtime.install("vision.ocr", source=source.as_uri(), sha256=checksum)
            artifact = Path(runtime.cache.installation("vision.ocr")["artifact_path"])
            artifact.write_bytes(b"tampered")
            item = next(item for item in runtime.models() if item["capability"] == "vision.ocr")
            self.assertEqual(item["status"], "corrupt")
            doctor = next(item for item in runtime.doctor()["capabilities"] if item["capability"] == "vision.ocr")
            self.assertEqual(doctor["status"], "corrupt")

    def test_http_rejects_oversized_and_non_json_bodies(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = SpecialistRuntime(home=Path(temp) / "home")
            handler = type("Handler", (RuntimeRequestHandler,), {"runtime": runtime})
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            server.api_token = None
            server.max_request_bytes = 32
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}/v1/vision/ocr"
            try:
                request = urllib.request.Request(url, data=b"x" * 64, headers={"Content-Type": "application/json"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(caught.exception.code, 413)
                request = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "text/plain"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(caught.exception.code, 415)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                runtime.close()

    def test_http_concurrency_returns_busy_instead_of_queueing_unboundedly(self):
        class SlowRuntime:
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()

            def run(self, _capability, _path, _options):
                self.started.set()
                self.release.wait(2)
                return {"capability": "vision.ocr", "provider": "test", "model": "test", "input": {"type": "image", "path": "x"}, "result": {}, "performance": {"latency_ms": 1}, "warnings": [], "error": None}

        runtime = SlowRuntime()
        handler = type("Handler", (RuntimeRequestHandler,), {"runtime": runtime})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.api_token = None
        server.max_request_bytes = 1024
        server.request_semaphore = threading.BoundedSemaphore(1)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/v1/vision/ocr"
        payload = json.dumps({"path": "input.txt"}).encode()
        first_result = {}

        def first_request():
            try:
                request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=3) as response:
                    first_result["status"] = response.status
            except Exception as exc:
                first_result["error"] = exc

        first = threading.Thread(target=first_request)
        first.start()
        self.assertTrue(runtime.started.wait(1))
        request = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 429)
        finally:
            runtime.release.set()
            first.join(timeout=3)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(first_result.get("status"), 200)

    def test_http_process_handles_sigterm_after_loading_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.txt"
            source.write_text("shutdown", encoding="utf-8")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            environment = os.environ.copy()
            environment["SPECIALIST_HOME"] = str(root / "home")
            process = subprocess.Popen([sys.executable, "-m", "specialist", "serve", "--host", "127.0.0.1", "--port", str(port)], cwd=Path(__file__).parents[1], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = process.stdout.readline()
                self.assertIn("listening", line)
                request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/vision/ocr", data=json.dumps({"path": str(source)}).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                process.terminate()
                self.assertEqual(process.wait(timeout=5), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()


if __name__ == "__main__":
    unittest.main()
