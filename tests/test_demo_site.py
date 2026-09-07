"""Guard the publication boundary for real CLI demonstration evidence."""

import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("build_demo_site", SCRIPTS / "build_demo_site.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoEvidenceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
