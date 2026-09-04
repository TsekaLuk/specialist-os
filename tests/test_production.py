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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from specialist.cache import Cache
from specialist.environments import ProviderEnvironmentManager
from specialist.models import ModelArtifactError, ModelManager
from specialist.registry import CAPABILITIES, REGISTRY_DOCUMENT
from specialist.runtime import SpecialistRuntime
from specialist.server import RuntimeRequestHandler
from specialist.providers.optional import CommandDocumentProvider, OmniParserProvider, OptionalProvider, PaddleOCRProvider, WhisperCppProvider
from specialist.providers.optional_expansion import PyannoteProvider


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
        self.assertGreaterEqual(len(CAPABILITIES), 56)
        self.assertTrue({"human.pose", "speech.diarize", "vision.search", "identity.face.verify", "media.probe"}.issubset(CAPABILITIES))
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
                    if spec.provider == "fish_audio" or model.artifact_kind == "server":
                        self.assertIsNone(model.artifact_url)
                        self.assertIsNone(model.artifact_sha256)
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

    def test_model_download_retries_transport_and_checksum_failures(self):
        payload = b"verified model artifact"

        class FlakyArtifactHandler(BaseHTTPRequestHandler):
            attempts = 0
            ranges = []

            def do_GET(self):
                type(self).attempts += 1
                type(self).ranges.append(self.headers.get("Range"))
                if self.attempts == 1:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload[:8])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                if self.attempts == 2:
                    body = b"x" * (len(payload) - 8)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes 8-{len(payload) - 1}/{len(payload)}")
                else:
                    body = payload
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), FlakyArtifactHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                destination = Path(temp) / "model.bin"
                expected = hashlib.sha256(payload).hexdigest()
                result = ModelManager(Cache(Path(temp) / "home"), timeout=2).download(
                    f"http://127.0.0.1:{server.server_port}/model.bin",
                    destination,
                    expected_sha256=expected,
                )
                self.assertEqual(destination.read_bytes(), payload)
                self.assertEqual(result["sha256"], expected)
                self.assertEqual(FlakyArtifactHandler.attempts, 3)
                self.assertEqual(FlakyArtifactHandler.ranges, [None, "bytes=8-", None])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

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

    def test_runtime_reuses_ready_provider_environment_without_install_flag(self):
        environment_python = "/tmp/omniparser-provider/bin/python"

        def environment_status(_manager, provider):
            if provider == "omniparser":
                return {"provider": provider, "status": "ready", "python": environment_python}
            return {"provider": provider, "status": "not installed"}

        with tempfile.TemporaryDirectory() as temp, patch.object(ProviderEnvironmentManager, "status", environment_status):
            runtime = SpecialistRuntime(home=Path(temp) / "home", backend="real", isolate=True)
            try:
                worker = runtime.providers["screen.parse"]
                self.assertEqual(worker.command[0], environment_python)
                self.assertEqual(worker.env["PATH"].split(os.pathsep)[0], "/tmp/omniparser-provider/bin")
            finally:
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

    def test_mineru_normalizes_structured_content_list(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = [
                {"type": "table", "page_idx": 0, "bbox": [1, 2, 3, 4], "table_body": "<table><tr><td>A</td></tr></table>", "table_caption": ["Results"], "table_footnote": [], "img_path": "images/table.jpg"},
                {"type": "image", "page_idx": 1, "bbox": [5, 6, 7, 8], "image_caption": ["Architecture"], "image_footnote": ["Source"], "img_path": "images/figure.jpg"},
                {"type": "equation", "page_idx": 2, "bbox": [9, 10, 11, 12], "text": "x^2", "text_format": "latex", "img_path": "images/equation.jpg"},
            ]
            (root / "report_content_list.json").write_text(json.dumps(content), encoding="utf-8")
            pages, tables, figures, formulas = CommandDocumentProvider._structure(root)
            self.assertEqual(pages, 3)
            self.assertEqual(tables[0]["html"], "<table><tr><td>A</td></tr></table>")
            self.assertEqual(figures[0]["caption"], ["Architecture"])
            self.assertEqual(formulas[0]["text"], "x^2")

    def test_mineru_rejects_untyped_and_remote_options_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.pdf"
            source.write_bytes(b"pdf")
            cache = Cache(root / "home")
            provider = CommandDocumentProvider(command="/usr/bin/true")
            provider._cache = cache
            provider._allow_unverified_models = True
            with self.assertRaises(Exception) as caught:
                provider.infer(source, {"start": "0"}, cache)
            self.assertEqual(caught.exception.code, "invalid_options")
            with self.assertRaises(Exception) as caught:
                provider.infer(source, {"backend": "vlm-http-client", "server_url": "https://example.com"}, cache)
            self.assertEqual(caught.exception.code, "remote_not_allowed")

    def test_omniparser_validates_options_and_merges_real_output_shapes(self):
        with self.assertRaises(Exception) as caught:
            OmniParserProvider._number_option({"max_elements": True}, "max_elements", 300, 1, 1000, integer=True)
        self.assertEqual(caught.exception.code, "invalid_options")
        elements = OmniParserProvider._merge_elements(
            [{"type": "text", "bbox": [0.1, 0.1, 0.2, 0.2], "content": "Save"}],
            [{"type": "icon", "bbox": [0.09, 0.09, 0.21, 0.21], "content": None}],
            0.7,
        )
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["content"], "Save")

    def test_omniparser_environment_and_bundle_pin_offline_florence_code(self):
        from specialist.environments import PROVIDER_REQUIREMENTS

        requirements = PROVIDER_REQUIREMENTS["omniparser"]
        self.assertIn("transformers==4.49.0", requirements)
        self.assertIn("timm==1.0.20", requirements)
        self.assertIn("einops==0.8.0", requirements)
        artifact_files = {
            item["path"]: item
            for item in REGISTRY_DOCUMENT["capabilities"]
            if item["name"] == "screen.parse"
            for item in item["models"][0]["artifact"]["files"]
        }
        self.assertIn("processor/processing_florence2.py", artifact_files)
        self.assertIn("icon_caption/configuration_florence2.py", artifact_files)
        self.assertIn("icon_caption/modeling_florence2.py", artifact_files)
        self.assertTrue(all("/resolve/" in item["url"] and "/resolve/main/" not in item["url"] for item in artifact_files.values()))

    def test_pyannote_four_result_objects_normalize_to_sorted_timeline(self):
        class Turn:
            def __init__(self, start, end):
                self.start = start
                self.end = end

        class Annotation:
            def itertracks(self, yield_label=False):
                self.yield_label = yield_label
                return iter([(Turn(2, 3), "track-b", "SPEAKER_01"), (Turn(0, 1), "track-a", "SPEAKER_00")])

        class Result:
            speaker_diarization = Annotation()
            exclusive_speaker_diarization = Annotation()

        segments = PyannoteProvider._normalize_segments(Result())
        exclusive = PyannoteProvider._normalize_segments(Result(), exclusive=True)
        self.assertEqual([item["speaker"] for item in segments], ["SPEAKER_00", "SPEAKER_01"])
        self.assertEqual(exclusive[0]["start"], 0.0)

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
                caught.exception.close()
                request = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "text/plain"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=2)
                self.assertEqual(caught.exception.code, 415)
                caught.exception.close()
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
            caught.exception.close()
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
