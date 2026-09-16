"""The HTTP readiness probe tests reachability; the CLI self-check does not.

`/ready` exists so an orchestrator can decide whether to send traffic here, so
it contacts declared endpoints. `specialist doctor` and the Python
`readiness()` default stay unprobed, because blocking an interactive report on
an unreachable LAN host is worse than admitting it was not checked.
"""

import io
import json
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from specialist import cli
from specialist.provider_manifest import ProviderManifest
from specialist.registry import CAPABILITIES
from specialist.remote import RemoteNodeProvider
from specialist.requirements import probe_endpoint_url
from specialist.runtime import READINESS_ENDPOINT_TIMEOUT, SpecialistRuntime
from specialist.server import RuntimeRequestHandler


class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal stand-in for a reachable node, so no patching is required."""

    def log_message(self, *_args):
        return

    def do_GET(self):
        body = json.dumps({"status": "ok"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(handler_class, runtime=None):
    handler = type("Handler", (handler_class,), {"runtime": runtime}) if runtime is not None else handler_class
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.api_token = None
    server.max_request_bytes = 1024 * 1024
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class ReadinessEndpointProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"

    def tearDown(self):
        self.temp.cleanup()

    def _single_capability(self):
        """Narrow the readiness loop so the endpoint is the only variable."""
        return patch.dict("specialist.runtime.CAPABILITIES", {"vision.ocr": CAPABILITIES["vision.ocr"]}, clear=True)

    def _ready_status(self, endpoint):
        runtime = SpecialistRuntime(home=self.home, backend="fallback",
                                    provider_overrides={"vision.ocr": RemoteNodeProvider("node-1", "vision.ocr", endpoint)})
        server, thread = _serve(RuntimeRequestHandler, runtime)
        try:
            with self._single_capability():
                request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/ready")
                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as error:
                    payload = json.loads(error.read())
                    error.close()
                    return error.code, payload
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            runtime.close()

    def test_ready_returns_503_when_a_registered_endpoint_is_unreachable(self):
        # Port 9 (discard) is closed on the loopback interface, so the probe
        # fails immediately instead of relying on a patched client.
        status, payload = self._ready_status("http://127.0.0.1:9")
        self.assertEqual(status, 503)
        self.assertFalse(payload["accepting_requests"])
        state = next(item for item in payload["details"] if item["capability"] == "vision.ocr")
        self.assertEqual(state["status"], "unavailable")
        self.assertEqual(state["check"]["endpoint_probe"]["status"], "unreachable")

    def test_ready_returns_200_when_the_registered_endpoint_is_healthy(self):
        health, health_thread = _serve(_HealthHandler)
        try:
            status, payload = self._ready_status(f"http://127.0.0.1:{health.server_port}")
        finally:
            health.shutdown()
            health.server_close()
            health_thread.join(timeout=2)
        self.assertEqual(status, 200)
        self.assertTrue(payload["accepting_requests"])
        state = next(item for item in payload["details"] if item["capability"] == "vision.ocr")
        self.assertEqual(state["status"], "ready")
        self.assertEqual(state["check"]["endpoint_probe"]["status"], "reachable")

    def test_capabilities_sharing_one_endpoint_cost_one_probe(self):
        shared = "http://127.0.0.1:9"
        capabilities = ["vision.ocr", "vision.detect", "vision.segment", "audio.transcribe"]
        overrides = {name: RemoteNodeProvider("node-1", name, shared) for name in capabilities}
        overrides["vision.depth"] = RemoteNodeProvider("node-2", "vision.depth", "http://127.0.0.1:10")
        runtime = SpecialistRuntime(home=self.home, backend="fallback", provider_overrides=overrides)
        calls = []

        def record(request, *args, **kwargs):
            # The runtime swallows provider self-check exceptions, so the call
            # is counted rather than asserted inline.
            calls.append((getattr(request, "full_url", request), kwargs.get("timeout")))
            raise OSError("connection refused")

        try:
            with patch("urllib.request.urlopen", side_effect=record):
                readiness = runtime.readiness(probe_endpoints=True)
        finally:
            runtime.close()
        # Four capabilities on one node cost one probe; the second node and the
        # Fish Audio server (two capabilities, one endpoint) cost one each.
        self.assertEqual([url for url, _timeout in calls].count(f"{shared}/health"), 1, calls)
        self.assertEqual(len(calls), len(set(url for url, _timeout in calls)), calls)
        self.assertEqual(len(calls), 3, calls)
        self.assertEqual({timeout for _url, timeout in calls}, {READINESS_ENDPOINT_TIMEOUT})
        self.assertIn(f"{shared}/health", readiness["probed_endpoints"])
        self.assertIn("http://127.0.0.1:10/health", readiness["probed_endpoints"])
        for name in capabilities:
            state = next(item for item in readiness["details"] if item["capability"] == name)
            self.assertEqual(state["status"], "unavailable", name)

    def test_python_readiness_default_probes_nothing(self):
        runtime = SpecialistRuntime(home=self.home, backend="fallback",
                                    provider_overrides={"vision.ocr": RemoteNodeProvider("node-1", "vision.ocr", "http://127.0.0.1:9")})
        calls = []

        def record(*args, **kwargs):
            calls.append(args)
            raise OSError("connection refused")

        try:
            with patch("urllib.request.urlopen", side_effect=record):
                readiness = runtime.readiness()
        finally:
            runtime.close()
        self.assertEqual(calls, [], "the Python readiness default must not contact an endpoint")
        self.assertEqual(readiness["probed_endpoints"], [])
        state = next(item for item in readiness["details"] if item["capability"] == "vision.ocr")
        self.assertEqual(state["check"]["endpoint_probe"]["status"], "unprobed")
        self.assertNotEqual(state["status"], "unavailable")

    def test_cli_doctor_issues_no_http_calls(self):
        home = Path(self.temp.name) / "cli-home"
        registry_runtime = SpecialistRuntime(home=home, backend="fallback")
        try:
            from specialist.node import ComputeNode

            registry_runtime.nodes.register(ComputeNode.create(
                "offline-node", capabilities=("vision.ocr", "vision.detect"), local=False,
                metadata={"endpoint": "http://127.0.0.1:9"}))
        finally:
            registry_runtime.close()
        calls = []

        def record(*args, **kwargs):
            calls.append(args)
            raise OSError("connection refused")

        for argv in (["--home", str(home), "doctor"], ["--home", str(home), "doctor", "--json"]):
            calls.clear()
            stream = io.StringIO()
            with patch("urllib.request.urlopen", side_effect=record), redirect_stdout(stream):
                cli.main(argv)
            self.assertEqual(calls, [], f"{argv} must not contact an endpoint")


class _UnhealthyHandler(BaseHTTPRequestHandler):
    """A node that answers but reports itself unhealthy. Up is not healthy."""

    def log_message(self, *_args):
        return

    def do_GET(self):
        body = json.dumps({"status": "degraded", "reason": "gpu fell over"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HealthPredicateTests(unittest.TestCase):
    """The bounded probe keeps the predicate the provider applies itself."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"

    def tearDown(self):
        self.temp.cleanup()

    def test_ready_returns_503_when_the_endpoint_answers_but_reports_unhealthy(self):
        node, node_thread = _serve(_UnhealthyHandler)
        try:
            endpoint = f"http://127.0.0.1:{node.server_port}"
            # The provider's own self-check refuses this node, so the readiness
            # route must not accept it on reachability alone.
            self.assertEqual(RemoteNodeProvider("node-1", "vision.ocr", endpoint).doctor({})["status"], "not ready")
            status, payload = ReadinessEndpointProbeTests._ready_status(self, endpoint)
        finally:
            node.shutdown()
            node.server_close()
            node_thread.join(timeout=2)
        self.assertEqual(status, 503)
        state = next(item for item in payload["details"] if item["capability"] == "vision.ocr")
        self.assertEqual(state["status"], "unavailable")
        probe = state["check"]["endpoint_probe"]
        self.assertEqual(probe["status"], "unhealthy", probe)
        self.assertIn("degraded", probe["reason"])
        self.assertEqual(state["check"]["error"]["code"], "endpoint_unhealthy")

    def test_remote_node_predicate_matches_its_own_doctor(self):
        expect = RemoteNodeProvider("node-1", "vision.ocr", "http://127.0.0.1:9").doctor_endpoint()["expect"]
        self.assertEqual(expect["status"], 200)
        self.assertEqual((expect["json_field"], expect["accept"]), ("status", ["ok"]))

    def test_fish_audio_predicate_matches_its_client_contract(self):
        from specialist.providers.fish_audio.provider import FishAudioProvider

        descriptor = FishAudioProvider().doctor_endpoint()
        self.assertTrue(descriptor["url"].endswith("/v1/health"))
        self.assertEqual(descriptor["expect"]["status"], 200)
        self.assertEqual(descriptor["expect"]["json_field"], "status")
        # FishAudioClient.health accepts exactly these values and nothing else.
        self.assertEqual(sorted(descriptor["expect"]["accept"]), ["healthy", "ok", "ready"])

    def test_probe_applies_the_declared_predicate_to_a_real_response(self):
        node, node_thread = _serve(_UnhealthyHandler)
        try:
            url = f"http://127.0.0.1:{node.server_port}/health"
            strict = probe_endpoint_url(url, timeout=2, expect={"status": 200, "json_field": "status", "accept": ["ok"]})
            lenient = probe_endpoint_url(url, timeout=2)
        finally:
            node.shutdown()
            node.server_close()
            node_thread.join(timeout=2)
        self.assertEqual((strict[0], strict[1]), (False, "unhealthy"))
        # Without a declared predicate only reachability is claimed, which is
        # why every networked provider declares one.
        self.assertTrue(lenient[0])

    def test_one_url_with_different_credentials_is_probed_separately(self):
        calls = []

        def record(request, *_args, **_kwargs):
            calls.append(request.get_header("Authorization"))
            raise OSError("connection refused")

        cache = {}
        with patch("urllib.request.urlopen", side_effect=record):
            probe_endpoint_url("http://127.0.0.1:9/health", timeout=0.2, headers={"Authorization": "Bearer first"}, probe_cache=cache)
            probe_endpoint_url("http://127.0.0.1:9/health", timeout=0.2, headers={"Authorization": "Bearer second"}, probe_cache=cache)
            probe_endpoint_url("http://127.0.0.1:9/health", timeout=0.2, headers={"Authorization": "Bearer first"}, probe_cache=cache)
        # Same URL, different credentials: two distinct probes, and the repeat
        # of the first credential is served from the cache.
        self.assertEqual(calls, ["Bearer first", "Bearer second"], calls)
        self.assertEqual(len(cache), 2, cache)

    def test_a_token_never_reaches_the_readiness_report(self):
        secret = "super-secret-node-token"
        runtime = SpecialistRuntime(home=self.home, backend="fallback",
                                    provider_overrides={"vision.ocr": RemoteNodeProvider("node-1", "vision.ocr", "http://127.0.0.1:9", token=secret)})
        try:
            with self._single_capability():
                readiness = runtime.readiness(probe_endpoints=True)
                report = runtime.doctor(probe_endpoints=True)
        finally:
            runtime.close()
        for payload in (readiness, report):
            self.assertNotIn(secret, json.dumps(payload, default=str))
        self.assertEqual(readiness["probed_endpoints"], ["http://127.0.0.1:9/health"])

    def _single_capability(self):
        return patch.dict("specialist.runtime.CAPABILITIES", {"vision.ocr": CAPABILITIES["vision.ocr"]}, clear=True)


class ManifestFailureIsolationTests(unittest.TestCase):
    """One bad manifest drops its own requirements, never everyone else's."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"

    def tearDown(self):
        self.temp.cleanup()

    def _install_manifests(self):
        runtime = SpecialistRuntime(home=self.home, backend="fallback")
        try:
            runtime.provider_catalog.install(ProviderManifest.from_dict({
                "provider": "good-provider",
                "version": "1.0.0",
                "capabilities": ["vision.detect"],
                "capability": "vision.detect",
                "runtime": {},
                "models": {},
                "metrics": {},
                "license": {},
                "platform": {},
                "requirements": [{"kind": "binary", "name": "definitely-not-installed-binary", "purpose": "run the tool"}],
            }))
            broken = runtime.provider_catalog.root / "broken-provider" / "manifest.json"
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text("{ this is not json", encoding="utf-8")
            return broken
        finally:
            runtime.close()

    def test_a_malformed_manifest_only_drops_its_own_requirements(self):
        broken = self._install_manifests()
        runtime = SpecialistRuntime(home=self.home, backend="fallback")
        try:
            report = runtime.doctor()
            readiness = runtime.readiness()
            good = runtime._provider_requirements("good-provider")
            missing = runtime._provider_requirements("broken-provider")
            builtin = runtime._provider_requirements("whisper.cpp")
        finally:
            runtime.close()
        self.assertEqual([item.name for item in good], ["definitely-not-installed-binary"])
        self.assertEqual(missing, ())
        self.assertTrue(builtin, "a bad third-party manifest must not hide builtin prerequisites")
        warning = next(item for item in report["warnings"] if str(broken) in item)
        self.assertIn("Skipped unreadable provider manifest", warning)
        self.assertIn(warning, readiness["warnings"])


if __name__ == "__main__":
    unittest.main()
