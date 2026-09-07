"""Experimental routes remain explicit, fail closed, and do not expand Core."""

from argparse import Namespace
from pathlib import Path
import tempfile
import unittest

from specialist.core import CORE_CAPABILITIES
from specialist.experimental.spatial import execute


class ExperimentalTests(unittest.TestCase):
    def test_wrong_checkpoint_fails_without_touching_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "input.png").write_bytes(b"invalid input")
            (root / "model.pt").write_bytes(b"invalid checkpoint")
            output = root / "output"
            output.mkdir()
            (output / "result.json").write_text("preserve")
            args = Namespace(experiment="scene-geometry", source=root, checkpoint=root, input=root / "input.png", output_dir=output, device="cpu", resolution=128, home=root / "home")
            result = execute(args)
            self.assertIsNotNone(result["error"])
            self.assertIn("SHA256", result["error"]["message"])
            self.assertEqual((output / "result.json").read_text(), "preserve")
            self.assertFalse(result["core"])
            self.assertNotIn(result["capability"], CORE_CAPABILITIES)
            self.assertEqual(result["artifacts"], [])


if __name__ == "__main__":
    unittest.main()
