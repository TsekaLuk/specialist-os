from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
import shutil

try:
    from .support import ROOT
except ImportError:
    from support import ROOT


@unittest.skipUnless(os.environ.get("SPECIALIST_RUN_PACKAGE_E2E") == "1", "set SPECIALIST_RUN_PACKAGE_E2E=1 to run the wheel installation E2E")
class PackageE2ETests(unittest.TestCase):
    def test_built_wheel_runs_without_checkout_or_runtime_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            dist.mkdir()
            build_environment = os.environ.copy()
            build_environment.pop("PYTHONPATH", None)
            build_module = importlib.util.find_spec("build")
            has_build_command = bool(build_module and build_module.origin and (Path(build_module.origin).parent / "__main__.py").is_file())
            if has_build_command:
                build_command = [sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(dist), str(ROOT)]
            elif shutil.which("uv"):
                build_command = ["uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)]
            else:
                self.fail("package E2E requires python-build or uv")
            build = subprocess.run(
                build_command,
                cwd=ROOT.parent,
                env=build_environment,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            wheels = list(dist.glob("*.whl"))
            self.assertEqual(len(wheels), 1, build.stdout + build.stderr)

            venv_dir = root / "venv"
            venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
            python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            install = subprocess.run(
                [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)

            home = root / "installed-home"
            run_cwd = root / "run"
            run_cwd.mkdir()
            environment = os.environ.copy()
            environment.pop("PYTHONPATH", None)
            environment["SPECIALIST_HOME"] = str(home)
            capabilities = subprocess.run(
                [str(python), "-m", "specialist", "--home", str(home), "capabilities"],
                cwd=run_cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(capabilities.returncode, 0, capabilities.stdout + capabilities.stderr)
            installed_capabilities = json.loads(capabilities.stdout)
            self.assertEqual(len(installed_capabilities), 56)
            capability_names = {item["capability"] for item in installed_capabilities}
            self.assertTrue(
                {
                    "human.pose",
                    "speech.diarize",
                    "vision.search",
                    "identity.face.verify",
                    "media.video.transcode",
                    "vision.human_state",
                }.issubset(capability_names)
            )

            source = root / "installed.txt"
            source.write_text("installed package", encoding="utf-8")
            ocr = subprocess.run(
                [str(python), "-m", "specialist", "--home", str(home), "ocr", str(source), "--json"],
                cwd=run_cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(ocr.returncode, 0, ocr.stdout + ocr.stderr)
            self.assertEqual(json.loads(ocr.stdout)["result"]["blocks"][0]["text"], "installed package")


if __name__ == "__main__":
    unittest.main()
