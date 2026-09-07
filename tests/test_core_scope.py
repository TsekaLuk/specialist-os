import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from specialist.core import CORE_CAPABILITIES, CORE_FAMILIES, CORE_FAMILY_BY_CAPABILITY, core_install_targets
from specialist.environments import PROVIDER_REQUIREMENTS
from specialist.packs import PACKS, get_pack
from specialist.registry import BUNDLES, CAPABILITIES, get_spec, registry_snapshot


class CoreScopeTests(unittest.TestCase):
    def test_new_registry_names_do_not_expand_core_installation(self):
        names = [*CAPABILITIES, "spatial.geometry", "generate.3d", "experimental.spatial.camera_pose", "vision.future"]
        self.assertEqual(core_install_targets(names), BUNDLES["core"])
        self.assertEqual(core_install_targets(reversed(names)), list(reversed(BUNDLES["core"])))

    def test_frozen_baseline_has_15_families_and_56_unique_apis(self):
        self.assertEqual(len(CORE_FAMILIES), 15)
        self.assertEqual(len(CORE_CAPABILITIES), 56)
        self.assertEqual(sum(map(len, CORE_FAMILIES.values())), 56)
        self.assertEqual(set(BUNDLES["core"]), CORE_CAPABILITIES)
        self.assertTrue(CORE_CAPABILITIES.issubset(CAPABILITIES))
        with self.assertRaises(TypeError):
            CORE_FAMILIES["spatial"] = ("spatial.geometry",)

    def test_core_install_targets_exclude_heavy_and_experimental_providers(self):
        self.assertEqual(set(get_pack("core").capabilities), CORE_CAPABILITIES)
        self.assertEqual(get_pack("all"), get_pack("core"))
        for name in BUNDLES["core"]:
            self.assertFalse(name.startswith(("generate.", "experimental.", "spatial.")))
            spec = CAPABILITIES[name]
            requirements = " ".join(PROVIDER_REQUIREMENTS.get(spec.optional_dependency, []))
            for heavy in ("hunyuan", "trellis", "tripo", "meshy", "open3d", "vggt", "moge"):
                self.assertNotIn(heavy, requirements.lower())
                self.assertNotIn(heavy, spec.provider.lower())

    def test_depth_pack_and_aliases_preserve_existing_contracts(self):
        self.assertEqual(get_pack("spatial"), get_pack("depth-vision"))
        self.assertNotIn("spatial", {pack.name for pack in PACKS})
        self.assertEqual(get_pack("depth-vision").capabilities, ("vision.depth", "vision.detect", "vision.segment"))
        for alias in ("depth", "spatial.depth", "spatial_depth", "vision.depth"):
            self.assertEqual(get_spec(alias).name, "vision.depth")
        for name in ("vision.geometry.solve_pnp", "vision.geometry.calibrate_camera", "vision.geometry.homography"):
            self.assertIn(name, CORE_FAMILIES["geometry"])

    def test_discovery_reports_core_family_without_changing_schemas(self):
        for item in registry_snapshot():
            self.assertEqual(item["core"], item["capability"] in CORE_CAPABILITIES)
            self.assertEqual(item["core_family"], CORE_FAMILY_BY_CAPABILITY.get(item["capability"]))
            self.assertEqual(item["output_schema"], get_spec(item["capability"]).output_schema)

    def test_cli_depth_discovery_and_pack_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = [sys.executable, "-m", "specialist", "--home", str(Path(tmp) / "home")]
            result = subprocess.run(command + ["capabilities", "spatial.depth"], capture_output=True, text=True, check=True, timeout=30)
            depth = json.loads(result.stdout)[0]
            self.assertTrue(depth["core"])
            self.assertEqual(depth["core_family"], "depth")
            self.assertFalse((Path(tmp) / "home").exists())
            result = subprocess.run(command + ["pack", "list"], capture_output=True, text=True, check=True, timeout=30)
            packs = {item["name"]: item for item in json.loads(result.stdout)}
            self.assertEqual(set(packs["core"]["capabilities"]), CORE_CAPABILITIES)
            self.assertIn("depth-vision", packs)
            self.assertNotIn("generate-3d", packs)

    def test_unavailable_3d_installation_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            for args in (["install", "generate-3d"], ["pack", "install", "generate-3d"], ["install", "experimental.spatial.geometry"]):
                result = subprocess.run([sys.executable, "-m", "specialist", "--home", tmp, *args], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("unknown", result.stderr.lower())
                self.assertNotIn('"status": "ready"', result.stdout)
