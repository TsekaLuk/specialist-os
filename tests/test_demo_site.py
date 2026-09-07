"""Guard the publication boundary for real CLI demonstration evidence."""

import importlib.util
import json
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("build_demo_site", SCRIPTS / "build_demo_site.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoEvidenceTests(unittest.TestCase):
    def test_replay_command_uses_real_routing_and_input_identity(self):
        envelope = json.loads((SCRIPTS.parent / 'docs/assets/e2e/vision-detect.json').read_text())
        command = demo.replay_command(envelope)
        self.assertIsNotNone(command)
        self.assertEqual(command[4], 'detect')
        routing = next(step for step in envelope['trace'] if step['stage'] == 'routing')
        self.assertEqual(json.loads(command[-1]), routing['requested']['options'])
        envelope['input']['sha256'] = '0' * 64
        self.assertIsNone(demo.replay_command(envelope))

    def test_only_uncached_success_is_publishable(self):
        evidence = {"provider": "opencv", "result": {"distance": 3}, "performance": {"cached": False}, "warnings": []}
        self.assertTrue(demo.successful(evidence))
        for changes in (
            {"error": {"code": "provider_failed"}},
            {"result": {"status": "degraded"}},
            {"result": None},
            {"performance": {"cached": True}},
            {"performance": {}},
            {"provider": None},
            {"warnings": ["fallback backend used"]},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(demo.successful({**evidence, **changes}))
        self.assertFalse(demo.successful({}))

    def test_recorded_cached_results_require_explicit_opt_in(self):
        evidence = {"provider": "yolo", "result": {"items": []}, "performance": {"cached": True}}
        self.assertFalse(demo.successful(evidence))
        self.assertTrue(demo.successful(evidence, allow_cached=True))
        self.assertFalse(demo.successful({**evidence, "error": {"code": "failed"}}, allow_cached=True))
        self.assertFalse(demo.successful({**evidence, "warnings": ["fallback backend used"]}, allow_cached=True))


if __name__ == "__main__":
    unittest.main()
