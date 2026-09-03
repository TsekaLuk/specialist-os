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
from types import ModuleType
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from pathlib import Path

from specialist.cache import Cache
from specialist.environments import ProviderEnvironmentManager
from specialist.models import ModelArtifactError, ModelManager
from specialist.registry import CAPABILITIES, REGISTRY_DOCUMENT
from specialist.runtime import SpecialistRuntime
from specialist.server import RuntimeRequestHandler
from specialist.providers.optional import CommandDocumentProvider, OptionalProvider, PaddleOCRProvider, WhisperCppProvider


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

    def test_optional_provider_rechecks_artifact_integrity_before_load(self):
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
            root = Path(temp)
            source = root / "model.bin"
            source.write_bytes(b"verified")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            cache = Cache(root / "home")
            cache.mark_installed("vision.ocr", "fake", "fake-model", artifact_path=source, sha256=digest)
            provider = FakeProvider()
            provider._cache = cache
            provider.infer(source, {}, cache)
            source.write_bytes(b"tampered")
            with self.assertRaises(Exception) as caught:
                provider._loaded = False
                provider.infer(source, {}, cache)
            self.assertEqual(caught.exception.code, "model_artifact_corrupt")

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

    def test_registry_artifacts_are_pinned_and_bundles_have_manifests(self):
        for spec in CAPABILITIES.values():
            for model in spec.models:
                if model.artifact_kind == "bundle":
                    self.assertGreaterEqual(len(model.artifact_files), 1)
                    self.assertTrue(all(item.url.startswith("https://") and len(item.sha256) == 64 for item in model.artifact_files))
                else:
                    self.assertIsNotNone(model.artifact_url, spec.name)
                    self.assertRegex(model.artifact_sha256 or "", r"^[0-9a-f]{64}$")

    def test_bundle_install_is_atomic_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_a = root / "weights.bin"
            source_b = root / "config.json"
            source_a.write_bytes(b"weights")
            source_b.write_text("{}", encoding="utf-8")
            files = []
            for relative, source in (("weights/weights.bin", source_a), ("config.json", source_b)):
                files.append({"path": relative, "url": source.as_uri(), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
            manager = ModelManager(Cache(root / "home"))
            result = manager.download_bundle(files, root / "home" / "models" / "bundle", entrypoint="weights/weights.bin")
            bundle = Path(result["path"])
            self.assertEqual(manager.verify_bundle(bundle)["entrypoint"], "weights/weights.bin")
            (bundle / "weights/weights.bin").write_bytes(b"tampered")
            with self.assertRaises(ModelArtifactError):
                manager.verify_bundle(bundle)

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

    def test_mineru_environment_verifies_the_published_module(self):
        # The wheel publishes ``mineru`` and the CLI entry point is also named
        # ``mineru``; the old magic_pdf probe incorrectly marked good envs as
        # corrupt and made production installs unusable.
        from specialist.environments import PROVIDER_IMPORTS, REQUIREMENT_IMPORTS

        self.assertEqual(PROVIDER_IMPORTS["mineru"], ["mineru"])
        self.assertEqual(REQUIREMENT_IMPORTS["mineru"], "mineru")

    def test_isolated_worker_path_contains_provider_environment_bin(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = SpecialistRuntime(home=Path(temp) / "home", backend="real")
            provider = CommandDocumentProvider(command="mineru")
            with patch.dict(
                os.environ,
                {
                    "SPECIALIST_MINERU_COMMAND": "/opt/mineru",
                    "SPECIALIST_MINERU_MODEL_DIR": "/opt/mineru-models",
                    "MINERU_TOOLS_CONFIG_JSON": "/opt/mineru.json",
                },
            ):
                worker = runtime._worker_provider("document.parse", provider, Path(temp) / "env" / "bin" / "python")
            self.assertTrue(worker.env["PATH"].split(os.pathsep)[0].endswith("env/bin"))
            self.assertEqual(worker.command[0], str(Path(temp) / "env" / "bin" / "python"))
            self.assertEqual(worker.env["SPECIALIST_MINERU_COMMAND"], "/opt/mineru")
            self.assertEqual(worker.env["SPECIALIST_MINERU_MODEL_DIR"], "/opt/mineru-models")
            self.assertEqual(worker.env["MINERU_TOOLS_CONFIG_JSON"], "/opt/mineru.json")
            runtime.close()

    def test_sam_worker_has_heavy_model_address_space_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = SpecialistRuntime(home=Path(temp) / "home", backend="real", isolate=True)
            worker = runtime.providers["vision.segment"]
            self.assertGreaterEqual(worker.memory_limit_bytes, 6 * 1024**3)
            runtime.close()

    def test_wheel_provider_requires_an_isolated_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = SpecialistRuntime(
                home=Path(temp) / "home",
                backend="real",
                provider_overrides={"document.parse": CommandDocumentProvider(command="/usr/bin/true")},
            )
            with self.assertRaises(Exception) as caught:
                runtime.install("document.parse", with_dependencies=False)
            self.assertEqual(caught.exception.code, "provider_environment_required")
            runtime.close()

    def test_paddleocr_uses_pinned_v5_bundle_without_extra_downloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            (bundle / "det").mkdir(parents=True)
            (bundle / "rec").mkdir(parents=True)
            manifest = bundle / "artifact-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            cache = Cache(root / "home")
            cache.mark_installed(
                "vision.ocr",
                "paddleocr",
                "pp-ocrv5-mobile",
                status="ready",
                artifact_path=bundle,
                artifact_kind="bundle",
                artifact_manifest=str(manifest),
                sha256="a" * 64,
            )
            captured = {}

            class FakeOCR:
                def __init__(self, **kwargs):
                    captured.update(kwargs)

            fake_module = ModuleType("paddleocr")
            fake_module.PaddleOCR = FakeOCR
            provider = PaddleOCRProvider()
            provider._cache = cache
            with patch.dict("sys.modules", {"paddleocr": fake_module, "paddle": ModuleType("paddle")}):
                with patch("specialist.providers.optional.importlib.util.find_spec", return_value=object()):
                    provider._load_model()
            self.assertEqual(captured["text_detection_model_name"], "PP-OCRv5_mobile_det")
            self.assertEqual(captured["text_recognition_model_name"], "PP-OCRv5_mobile_rec")
            self.assertFalse(captured["use_doc_orientation_classify"])
            self.assertFalse(captured["use_doc_unwarping"])
            self.assertFalse(captured["use_textline_orientation"])
            self.assertFalse(captured["enable_mkldnn"])

    def test_whisper_rejects_invalid_audio_and_removes_stale_sidecar(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = Cache(root / "home")
            model = root / "model.bin"
            model.write_bytes(b"model")
            digest = hashlib.sha256(model.read_bytes()).hexdigest()
            cache.mark_installed("audio.transcribe", "whisper.cpp", "ggml-base.en", status="ready", artifact_path=model, sha256=digest)
            invalid = root / "bad.wav"
            invalid.write_bytes(b"not wav")
            provider = WhisperCppProvider(binary="missing-whisper")
            provider._cache = cache
            with self.assertRaises(Exception) as caught:
                provider.infer(invalid, {}, cache)
            self.assertEqual(caught.exception.code, "dependency_missing")

            import wave

            audio = root / "sample.wav"
            with wave.open(str(audio), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b"\0\0" * 1600)
            sidecar = audio.with_suffix(".json")
            sidecar.write_text("{\"stale\": true}", encoding="utf-8")
            executable = root / "whisper-cli"
            executable.write_text("#!/bin/sh\nprintf '%s' '{\"segments\":[{\"timestamps\":{\"from\":0,\"to\":1},\"text\":\" hello \"}]}' > \"$4.json\"\n", encoding="utf-8")
            executable.chmod(0o755)
            provider = WhisperCppProvider(binary=str(executable))
            provider._cache = cache
            result, _warnings = provider.infer(audio, {}, cache)
            self.assertEqual(result["text"], "hello")
            self.assertEqual(result["segments"][0]["start"], 0)

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
