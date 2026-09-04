from __future__ import annotations

import base64
import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
import wave
import sys
import socket
from unittest.mock import patch

from specialist.runtime import SpecialistRuntime
from specialist.providers.fish_audio import FishAudioProvider
from specialist.providers.fish_audio.client import FishAudioClient, FishAudioError
from specialist.providers.fish_audio.lifecycle import FishAudioLifecycle


def _wav() -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 800)
    return stream.getvalue()


class _FishContractHandler(BaseHTTPRequestHandler):
    audio = _wav()
    malformed = False
    json_response = False
    last_request = None

    def do_GET(self):
        if self.path != "/v1/health":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        _FishContractHandler.last_request = json.loads(self.rfile.read(length))
        if self.malformed:
            body = b"not-audio"
            content_type = "audio/wav"
        elif self.json_response:
            body = json.dumps({"audio": base64.b64encode(self.audio).decode("ascii")}).encode("ascii")
            content_type = "application/json"
        else:
            body = self.audio
            content_type = "audio/wav"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class FishAudioProviderTests(unittest.TestCase):
    def setUp(self):
        import os

        self._environment = {
            key: os.environ.get(key)
            for key in ("SPECIALIST_FISH_AUDIO_URL", "SPECIALIST_FISH_AUDIO_START_POLICY")
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FishContractHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        import os

        self.server.shutdown()
        self.server.server_close()
        _FishContractHandler.malformed = False
        _FishContractHandler.json_response = False
        _FishContractHandler.last_request = None
        for key, value in self._environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _runtime(self, root: Path) -> SpecialistRuntime:
        import os

        os.environ["SPECIALIST_FISH_AUDIO_URL"] = f"http://127.0.0.1:{self.server.server_port}"
        os.environ["SPECIALIST_FISH_AUDIO_START_POLICY"] = "manual"
        return SpecialistRuntime(home=root / "home", backend="real")

    def test_synthesis_is_an_audio_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            runtime = self._runtime(root)
            try:
                result = runtime.run("speech.synthesize", text, {"text": "Hello", "profile": "quality"})
            finally:
                runtime.close()
            self.assertIsNone(result["error"], result)
            audio = result["result"]["audio"]
            self.assertTrue(audio["artifact"].startswith("artifact://"))
            self.assertNotIn("path", audio)
            self.assertEqual(runtime.artifacts.resolve(audio["artifact"]).read_bytes(), _wav())
            self.assertEqual(_FishContractHandler.last_request["text"], "Hello")
            self.assertEqual(result["performance"]["audio_duration_ms"], 100.0)
            self.assertGreaterEqual(result["performance"]["rtf"], 0)

    def test_json_base64_audio_payload_is_decoded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            _FishContractHandler.json_response = True
            runtime = self._runtime(root)
            try:
                result = runtime.run("speech.synthesize", text, {"text": "Hello", "profile": "quality"})
            finally:
                runtime.close()
            self.assertIsNone(result["error"], result)
            self.assertEqual(runtime.artifacts.resolve(result["result"]["audio"]["artifact"]).read_bytes(), _wav())

    def test_clone_requires_reference_and_never_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.wav"
            reference.write_bytes(_wav())
            runtime = self._runtime(root)
            try:
                result = runtime.run("speech.clone_voice", reference, {"text": "Hello", "reference_text": "Reference speech", "provider": "fish_audio"})
            finally:
                runtime.close()
            self.assertIsNone(result["error"], result)
            self.assertEqual(result["provider"], "fish_audio")
            self.assertIn("references", _FishContractHandler.last_request)
            self.assertEqual(_FishContractHandler.last_request["references"][0]["text"], "Reference speech")
            self.assertNotIn("reference_text", _FishContractHandler.last_request)

    def test_clone_accepts_artifact_uri_reference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.wav"
            reference.write_bytes(_wav())
            runtime = self._runtime(root)
            try:
                artifact = runtime.artifacts.put_file(reference, mime="audio/wav")
                result = runtime.run(
                    "speech.clone_voice",
                    artifact.uri,
                    {"text": "Hello", "reference_audio": artifact.uri, "provider": "fish_audio"},
                )
            finally:
                runtime.close()
            self.assertIsNone(result["error"], result)
            self.assertIn("references", _FishContractHandler.last_request)

    def test_style_and_stream_options_map_to_fish_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            runtime = self._runtime(root)
            try:
                result = runtime.run(
                    "speech.synthesize",
                    text,
                    {"text": "Hello", "style": {"instruction": "whisper softly"}, "language": "en", "stream": True, "provider": "fish_audio"},
                )
            finally:
                runtime.close()
            self.assertIsNone(result["error"], result)
            self.assertEqual(_FishContractHandler.last_request["text"], "[whisper softly] Hello")
            self.assertTrue(_FishContractHandler.last_request["streaming"])
            self.assertNotIn("language", _FishContractHandler.last_request)
            self.assertIn("detects language", result["warnings"][0])

    def test_streaming_rejects_non_wav_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            runtime = self._runtime(root)
            try:
                result = runtime.run(
                    "speech.synthesize",
                    text,
                    {"text": "Hello", "format": "ogg", "stream": True, "provider": "fish_audio"},
                )
            finally:
                runtime.close()
            self.assertEqual(result["error"]["code"], "invalid_audio_format")

    def test_provider_options_keep_generic_contract_fields_protected(self):
        client = FishAudioClient(f"http://127.0.0.1:{self.server.server_port}")
        with self.assertRaises(FishAudioError) as native_error:
            client.synthesize(text="Hello", provider_options={"native_text_controls": "false"})
        self.assertEqual(native_error.exception.code, "invalid_provider_options")
        with self.assertRaises(FishAudioError) as reserved_error:
            client.synthesize(text="Hello", provider_options={"stream": False})
        self.assertEqual(reserved_error.exception.code, "invalid_provider_options")

    def test_remote_server_is_not_gated_by_client_host_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            hardware = {"os": "Darwin 25", "architecture": "arm64", "memory_gb": 8, "memory_limit_gb": None, "cuda": False, "mps": True}
            class RemoteFishProvider(FishAudioProvider):
                @property
                def remote(self):
                    return True

            with patch.dict(os.environ, {"SPECIALIST_FISH_AUDIO_URL": f"http://127.0.0.1:{self.server.server_port}", "SPECIALIST_FISH_AUDIO_START_POLICY": "manual"}, clear=False), patch("specialist.runtime.detect_hardware", return_value=hardware):
                provider = RemoteFishProvider("speech.synthesize")
                runtime = SpecialistRuntime(home=root / "home", backend="real", provider_overrides={"speech.synthesize": provider})
                try:
                    result = runtime.run("speech.synthesize", text, {"text": "Hello", "profile": "quality", "allow_remote": True, "local_only": False})
                finally:
                    runtime.close()
            self.assertIsNone(result["error"], result)
            self.assertEqual(result["provider"], "fish_audio")

    def test_server_managed_provider_is_not_gated_by_client_host_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            hardware = {"os": "Darwin 25", "architecture": "arm64", "memory_gb": 8, "memory_limit_gb": None, "cuda": False, "mps": True}
            with patch.dict(os.environ, {"SPECIALIST_FISH_AUDIO_URL": f"http://127.0.0.1:{self.server.server_port}", "SPECIALIST_FISH_AUDIO_START_POLICY": "manual"}, clear=False), patch("specialist.runtime.detect_hardware", return_value=hardware):
                provider = FishAudioProvider("speech.synthesize")
                runtime = SpecialistRuntime(home=root / "home", backend="real", provider_overrides={"speech.synthesize": provider})
                try:
                    result = runtime.run("speech.synthesize", text, {"text": "Hello", "profile": "quality"})
                finally:
                    runtime.close()
            self.assertIsNone(result["error"], result)
            self.assertEqual(result["provider"], "fish_audio")

    def test_doctor_returns_structured_state_for_invalid_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hardware = {"os": "Darwin 25", "architecture": "arm64", "memory_gb": 8, "memory_limit_gb": None, "cuda": False, "mps": True}
            with patch.dict(os.environ, {"SPECIALIST_FISH_AUDIO_URL": "not-an-http-url"}, clear=False), patch("specialist.runtime.detect_hardware", return_value=hardware):
                runtime = SpecialistRuntime(home=root / "home", backend="real")
                try:
                    payload = runtime.doctor()
                finally:
                    runtime.close()
            fish = next(item for item in payload["capabilities"] if item["capability"] == "speech.synthesize")
            self.assertEqual(fish["status"], "unavailable")
            self.assertEqual(fish["error"]["code"], "provider_doctor_failed")

    def test_run_returns_structured_error_for_invalid_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            with patch.dict(os.environ, {"SPECIALIST_FISH_AUDIO_URL": "not-an-http-url"}, clear=False):
                runtime = SpecialistRuntime(home=root / "home", backend="real")
                try:
                    result = runtime.run("speech.synthesize", text, {"text": "Hello", "provider": "fish_audio", "fallback": False})
                finally:
                    runtime.close()
            self.assertEqual(result["error"]["code"], "routing_provider_error")

    def test_malformed_audio_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            _FishContractHandler.malformed = True
            runtime = self._runtime(root)
            try:
                result = runtime.run("speech.synthesize", text, {"text": "Hello", "provider": "fish_audio", "fallback": False})
            finally:
                runtime.close()
            self.assertIsNotNone(result["error"])
            self.assertIn(result["error"]["code"], {"malformed_audio", "fish_audio_protocol_error"})

    def test_malformed_audio_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "text.txt"
            text.write_text("Hello", encoding="utf-8")
            _FishContractHandler.malformed = True
            runtime = self._runtime(root)
            try:
                result = runtime.run("speech.synthesize", text, {"text": "Hello", "profile": "quality"})
            finally:
                runtime.close()
            self.assertIsNotNone(result["error"])
            self.assertIn(result["error"]["code"], {"malformed_audio", "fish_audio_protocol_error"})

    def test_voice_registry_is_explicit_and_provider_neutral(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.wav"
            reference.write_bytes(_wav())
            runtime = self._runtime(root)
            try:
                record = runtime.import_voice(reference, "me", provider_assets={"fish_audio": {"reference_id": "spk_test"}})
                self.assertEqual(record["uri"], "voice://me")
                self.assertEqual(runtime.list_voices()[0]["id"], "me")
            finally:
                runtime.close()

    def test_system_tts_route_uses_system_model_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="real")
            try:
                route = runtime.explain("speech.synthesize", {"provider": "system_tts"})
            finally:
                runtime.close()
            self.assertEqual(route["selected"]["model"], "system-default")
            self.assertEqual({item["model"] for item in route["candidates"]}, {"system-default"})

    def test_commercial_policy_selects_commercial_system_voice(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="real")
            try:
                route = runtime.explain("speech.synthesize", {"profile": "quality", "commercial_safe": True})
            finally:
                runtime.close()
            self.assertEqual(route["selected"]["provider"], "system_tts")
            self.assertTrue(route["selected"]["commercial"])
            fish = next(item for item in route["candidates"] if item["provider"] == "fish_audio")
            self.assertFalse(fish["allowed"])

    def test_alternate_provider_installation_keeps_model_identity_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="real")
            try:
                runtime.install("speech.synthesize", provider_override=runtime.providers["speech.synthesize@system_tts"])
                installation = runtime.cache.installation("speech.synthesize")
                self.assertEqual(installation["provider"], "system_tts")
                self.assertEqual(installation["model"], "system-default")
                route = runtime.explain("speech.synthesize")
            finally:
                runtime.close()
            selected = route["selected"]
            self.assertEqual(selected["provider"], "system_tts")
            self.assertEqual(selected["model"], "system-default")
            candidates = {(item["provider"], item["model"]) for item in route["candidates"]}
            self.assertIn(("fish_audio", "s2-pro"), candidates)
            self.assertIn(("system_tts", "system-default"), candidates)
            self.assertNotIn(("fish_audio", "system-default"), candidates)

    def test_isolated_alternate_provider_keeps_model_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="real", isolate=True)
            try:
                provider = runtime.providers["speech.synthesize@system_tts"]
                self.assertEqual(provider.preferred_model, "system-default")
                self.assertTrue(provider.commercial)
                runtime.install("speech.synthesize", provider_override=provider)
                installation = runtime.cache.installation("speech.synthesize")
            finally:
                runtime.close()
            self.assertEqual(installation["provider"], "system_tts")
            self.assertEqual(installation["model"], "system-default")

    def test_explicit_lifecycle_start_persists_and_stop_cleans_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "server.py"
            script.write_text(
                "from http.server import BaseHTTPRequestHandler, HTTPServer\n"
                "import sys\n"
                "class Handler(BaseHTTPRequestHandler):\n"
                "    def do_GET(self):\n"
                "        body = b'{\"status\":\"ok\"}'\n"
                "        self.send_response(200)\n"
                "        self.send_header('Content-Type', 'application/json')\n"
                "        self.send_header('Content-Length', str(len(body)))\n"
                "        self.end_headers()\n"
                "        self.wfile.write(body)\n"
                "    def log_message(self, *_args):\n"
                "        return\n"
                "HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()\n",
                encoding="utf-8",
            )
            probe = socket.socket()
            probe.bind(("127.0.0.1", 0))
            child_port = probe.getsockname()[1]
            probe.close()
            endpoint = f"http://127.0.0.1:{child_port}"
            state_path = root / "state.json"
            lifecycle = FishAudioLifecycle(
                FishAudioClient(endpoint, timeout_seconds=2),
                command=f"{sys.executable} {script} {child_port}",
                startup_timeout=5,
                state_path=state_path,
            )
            try:
                started = lifecycle.start(persist=True)
                self.assertTrue(started["started"])
                self.assertTrue(started["persistent"])
                self.assertIsNone(lifecycle.process)
                self.assertTrue(state_path.is_file())
                other = FishAudioLifecycle(FishAudioClient(endpoint, timeout_seconds=2), state_path=state_path)
                self.assertEqual(other.health()["status"], "ready")
                other.stop()
                self.assertFalse(state_path.exists())
            finally:
                lifecycle.stop()


if __name__ == "__main__":
    unittest.main()
