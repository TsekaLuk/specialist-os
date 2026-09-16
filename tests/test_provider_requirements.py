import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from specialist.cli import _print_capability_reason
from specialist.provider_manifest import ProviderManifest, builtin_manifests
from specialist.remote import RemoteNodeProvider
from specialist.requirements import ProviderRequirement, evaluate_requirements, probe_requirement
from specialist.runtime import SpecialistRuntime


class _FixtureProvider:
    """Installed, routable provider with no prerequisites of its own."""

    name = "fixture-provider"
    requires_verified_artifact = False
    model = "fixture-model"

    def doctor(self, _hardware):
        return {"status": "ready", "backend": "fixture"}


class RequirementModelTests(unittest.TestCase):
    def test_group_is_satisfied_when_any_member_is(self):
        requirements = (
            ProviderRequirement("binary", "definitely-not-installed-binary", "run the tool", group="tool"),
            ProviderRequirement("env", "SPECIALIST_TEST_TOOL", "run the tool", group="tool"),
        )
        report = evaluate_requirements(requirements, environ={"SPECIALIST_TEST_TOOL": "/opt/tool"})
        self.assertEqual([item["status"] for item in report["groups"]], ["satisfied"])
        self.assertEqual(report["unmet"], [])
        self.assertTrue(report["satisfied"])

    def test_group_with_no_satisfied_member_is_reported_once(self):
        requirements = (
            ProviderRequirement("binary", "definitely-not-installed-binary", "run the tool", group="tool"),
            ProviderRequirement("env", "SPECIALIST_TEST_TOOL", "run the tool", group="tool"),
        )
        report = evaluate_requirements(requirements, environ={"PATH": ""})
        self.assertEqual(len(report["unmet"]), 1)
        self.assertEqual(report["unmet"][0]["group"], "tool")
        self.assertEqual(len(report["unmet"][0]["sources"]), 2)

    def test_optional_missing_requirement_does_not_count_as_a_gap(self):
        report = evaluate_requirements(
            (ProviderRequirement("env", "SPECIALIST_TEST_OPTIONAL_TOKEN", "authenticate", optional=True),),
            environ={},
        )
        self.assertEqual(report["unmet"], [])
        self.assertTrue(report["satisfied"])
        self.assertEqual(len(report["unmet_optional"]), 1)

    def test_endpoint_is_declared_but_never_contacted_by_default(self):
        requirement = ProviderRequirement("endpoint", "http://127.0.0.1:9/health", "reach the server")

        def fail(*_args, **_kwargs):
            raise AssertionError("a self-check must not contact an endpoint by default")

        with patch("urllib.request.urlopen", side_effect=fail):
            probe = probe_requirement(requirement)
            report = evaluate_requirements((requirement,))
        self.assertIsNone(probe["ok"])
        self.assertFalse(probe["probed"])
        self.assertEqual([item["status"] for item in report["groups"]], ["unprobed"])
        self.assertEqual(report["unmet"], [])

    def test_endpoint_is_probed_only_with_the_explicit_opt_in(self):
        requirement = ProviderRequirement("endpoint", "http://127.0.0.1:9/health", "reach the server")
        calls = []

        def record(*args, **kwargs):
            calls.append(args)
            raise OSError("connection refused")

        with patch("urllib.request.urlopen", side_effect=record):
            probe = probe_requirement(requirement, probe_endpoints=True)
        self.assertEqual(len(calls), 1)
        self.assertIs(probe["ok"], False)
        self.assertIn("unreachable", probe["detail"])

    def test_binary_and_file_probes(self):
        with tempfile.TemporaryDirectory() as temporary:
            present = Path(temporary) / "present.json"
            present.write_text("{}", encoding="utf-8")
            self.assertTrue(probe_requirement(ProviderRequirement("file", str(present), "config"))["ok"])
            self.assertFalse(probe_requirement(ProviderRequirement("file", str(Path(temporary) / "absent.json"), "config"))["ok"])
        self.assertTrue(probe_requirement(ProviderRequirement("binary", "python3", "run"))["ok"])
        self.assertFalse(probe_requirement(ProviderRequirement("binary", "definitely-not-installed-binary", "run"))["ok"])


class ManifestRequirementTests(unittest.TestCase):
    def test_requirements_round_trip_through_manifest_data(self):
        manifest = ProviderManifest.from_dict({
            "provider": "demo",
            "version": "1",
            "capability": "vision.detect",
            "runtime": {},
            "models": {},
            "metrics": {},
            "license": {},
            "platform": {},
            "requirements": [{"kind": "env", "name": "DEMO_TOKEN", "purpose": "auth", "group": "credential"}],
        })
        self.assertEqual(manifest.requirements[0].group_key, "credential")
        restored = ProviderManifest.from_dict(manifest.to_dict())
        self.assertEqual(restored.requirements, manifest.requirements)

    def test_builtin_requirements_are_readable_without_importing_providers(self):
        manifests = {item.provider: item for item in builtin_manifests()}
        whisper = manifests["whisper.cpp"].requirements
        groups = {item.group_key for item in whisper}
        self.assertIn("whisper-binary", groups)
        self.assertEqual({item.kind for item in whisper if item.group_key == "whisper-binary"}, {"binary", "env"})
        fish = manifests["fish_audio"].requirements
        self.assertEqual([item.kind for item in fish if item.kind == "endpoint"], ["endpoint"])
        self.assertTrue(any(item.optional for item in fish))


class DoctorStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"

    def tearDown(self):
        self.temp.cleanup()

    def _runtime(self, provider):
        return SpecialistRuntime(home=self.home, backend="fallback", provider_overrides={"vision.ocr": provider})

    def test_installed_capability_with_an_unmet_requirement_is_degraded(self):
        runtime = self._runtime(_FixtureProvider())
        runtime._requirement_index = {"fixture-provider": (ProviderRequirement("binary", "definitely-not-installed-binary", "run the fixture", group="fixture-tool"),)}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
            readiness = runtime.readiness()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "degraded")
        self.assertIn("fixture-tool", item["reason"])
        self.assertEqual(item["requirements"]["unmet"][0]["group"], "fixture-tool")
        state = next(value for value in readiness["details"] if value["capability"] == "vision.ocr")
        self.assertEqual(state["status"], "degraded")

    def test_optional_missing_requirement_keeps_the_capability_ready(self):
        runtime = self._runtime(_FixtureProvider())
        runtime._requirement_index = {"fixture-provider": (ProviderRequirement("env", "SPECIALIST_TEST_ABSENT_TOKEN", "authenticate", optional=True),)}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "ready")

    def test_grouped_requirement_satisfied_by_one_member_reports_no_gap(self):
        runtime = self._runtime(_FixtureProvider())
        runtime._requirement_index = {"fixture-provider": (
            ProviderRequirement("binary", "definitely-not-installed-binary", "run the fixture", group="fixture-tool"),
            ProviderRequirement("binary", "python3", "run the fixture", group="fixture-tool"),
        )}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "ready")
        self.assertEqual(item["requirements"]["unmet"], [])

    def test_unavailable_provider_stays_unavailable_not_degraded(self):
        class UnreadyProvider(_FixtureProvider):
            def doctor(self, _hardware):
                return {"status": "not ready", "error": {"code": "fixture_unavailable", "message": "fixture provider is unavailable"}}

        runtime = self._runtime(UnreadyProvider())
        runtime._requirement_index = {"fixture-provider": (ProviderRequirement("binary", "definitely-not-installed-binary", "run the fixture"),)}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "unavailable")
        self.assertIn("fixture provider is unavailable", item["reason"])

    def test_doctor_does_not_contact_a_registered_remote_node(self):
        node = RemoteNodeProvider("node-1", "vision.ocr", "http://127.0.0.1:9", token=None)

        def fail(*_args, **_kwargs):
            raise AssertionError("doctor must not contact a remote node by default")

        runtime = self._runtime(node)
        try:
            with patch("urllib.request.urlopen", side_effect=fail):
                report = runtime.doctor()
                readiness = runtime.readiness()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["endpoint_probe"]["status"], "unprobed")
        self.assertNotEqual(item["status"], "unavailable")
        state = next(value for value in readiness["details"] if value["capability"] == "vision.ocr")
        self.assertEqual(state["check"]["endpoint_probe"]["status"], "unprobed")

    def test_remote_node_is_contacted_with_the_explicit_opt_in(self):
        node = RemoteNodeProvider("node-1", "vision.ocr", "http://127.0.0.1:9", token=None)
        calls = []

        def record(*args, **kwargs):
            calls.append(args)
            raise OSError("connection refused")

        runtime = self._runtime(node)
        try:
            with patch("urllib.request.urlopen", side_effect=record):
                report = runtime.doctor(probe_endpoints=True)
        finally:
            runtime.close()
        self.assertGreaterEqual(len(calls), 1)
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "unavailable")

    def test_fish_audio_endpoint_is_declared_but_unprobed_in_the_default_report(self):
        calls = []

        def record(*args, **kwargs):
            # A raised exception would be swallowed by the runtime's provider
            # guard, so the call is counted instead of asserted inline.
            calls.append(args)
            raise OSError("connection refused")

        runtime = SpecialistRuntime(home=self.home, backend="fallback")
        try:
            # The client calls ``urllib.request.urlopen``, so this patch covers
            # the lifecycle health check the default report must not trigger.
            with patch("urllib.request.urlopen", side_effect=record):
                report = runtime.doctor()
        finally:
            runtime.close()
        self.assertEqual(calls, [], "doctor must not contact the Fish Audio server by default")
        item = next(value for value in report["capabilities"] if value["capability"] == "speech.synthesize")
        self.assertEqual(item["endpoint_probe"]["status"], "unprobed")
        unprobed = {group["group"] for group in item["requirements"]["unprobed"]}
        self.assertIn("endpoint:SPECIALIST_FISH_AUDIO_URL", unprobed)
        self.assertEqual(item["requirements"]["unmet"], [])


class ProviderEnvironmentRequirementTests(unittest.TestCase):
    """A capability that works must never be reported as degraded."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "home"

    def tearDown(self):
        self.temp.cleanup()

    def test_binary_installed_only_in_the_provider_environment_is_not_a_gap(self):
        # An isolated worker prepends its provider environment to PATH, so a
        # console script installed there is invisible to the parent process.
        bin_dir = Path(self.temp.name) / "provider-env" / "bin"
        bin_dir.mkdir(parents=True)
        script = bin_dir / "fixture-console-script"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)

        class WorkerLikeProvider(_FixtureProvider):
            env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}

            def doctor(self, _hardware):
                return {"status": "ready", "backend": "isolated-worker"}

        runtime = SpecialistRuntime(home=self.home, backend="fallback", provider_overrides={"vision.ocr": WorkerLikeProvider()})
        runtime._requirement_index = {"fixture-provider": (ProviderRequirement("binary", "fixture-console-script", "run the fixture"),)}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "ready", item.get("reason"))
        self.assertEqual(item["requirements"]["unmet"], [])

    def test_dependency_free_fallback_does_not_inherit_the_real_prerequisites(self):
        # The fallback classes deliberately share the real provider name, so the
        # exemption has to key on the reported backend, not on the name.
        class FallbackProvider(_FixtureProvider):
            def doctor(self, _hardware):
                return {"status": "ready", "backend": "builtin-fallback"}

        runtime = SpecialistRuntime(home=self.home, backend="fallback", provider_overrides={"vision.ocr": FallbackProvider()})
        runtime._requirement_index = {"fixture-provider": (ProviderRequirement("binary", "definitely-not-installed-binary", "run the fixture"),)}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "ready")
        self.assertIsNone(item["requirements"])

    def test_a_real_backend_with_the_same_name_is_still_evaluated(self):
        # Guards the inverse of the exemption: only the dependency-free
        # fallback may skip its prerequisites.
        class RealProvider(_FixtureProvider):
            def doctor(self, _hardware):
                return {"status": "ready", "backend": "optional"}

        runtime = SpecialistRuntime(home=self.home, backend="fallback", provider_overrides={"vision.ocr": RealProvider()})
        runtime._requirement_index = {"fixture-provider": (ProviderRequirement("binary", "definitely-not-installed-binary", "run the fixture"),)}
        runtime.cache.mark_installed("vision.ocr", "fixture-provider", "fixture-model", status="ready")
        try:
            report = runtime.doctor()
        finally:
            runtime.close()
        item = next(value for value in report["capabilities"] if value["capability"] == "vision.ocr")
        self.assertEqual(item["status"], "degraded")


class HumanDoctorOutputTests(unittest.TestCase):
    def _render(self, item):
        stream = io.StringIO()
        with redirect_stdout(stream):
            _print_capability_reason(item)
        return stream.getvalue()

    def test_unmet_requirement_is_named_for_a_capability_that_is_not_ready(self):
        text = self._render({
            "status": "unavailable",
            "reason": "provider models are not configured",
            "requirements": {"unmet": [{"group": "tool", "label": "tool", "purpose": "run it", "sources": [{"kind": "binary", "name": "tool-cli"}]}], "unprobed": []},
        })
        self.assertIn("reason: provider models are not configured", text)
        self.assertIn("missing required prerequisite: tool (binary tool-cli)", text)

    def test_the_degraded_reason_is_not_printed_twice(self):
        text = self._render({
            "status": "degraded",
            "reason": "missing required prerequisite: tool (binary tool-cli) - run it",
            "requirements": {"unmet": [{"group": "tool", "label": "tool", "purpose": "run it", "sources": [{"kind": "binary", "name": "tool-cli"}]}], "unprobed": []},
        })
        self.assertEqual(text.count("tool-cli"), 1)

    def test_an_unprobed_endpoint_is_visible_on_a_ready_capability(self):
        text = self._render({
            "status": "ready",
            "requirements": {"unmet": [], "unprobed": [{"group": "endpoint:SERVER_URL", "label": None, "purpose": "reach the server", "sources": [{"kind": "endpoint", "name": "SERVER_URL"}]}]},
        })
        self.assertIn("not probed: endpoint SERVER_URL", text)


if __name__ == "__main__":
    unittest.main()
