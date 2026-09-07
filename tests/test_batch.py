import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from specialist.batch import load_requests
from specialist.runtime import SpecialistRuntime
from specialist.cache import Cache
from specialist.environments import ProviderEnvironmentManager
from specialist.environments import PROVIDER_REQUIREMENTS
from specialist.registry import get_spec


class BatchTests(unittest.TestCase):
    def test_vad_install_includes_provider_not_only_framework(self):
        spec = get_spec("audio.vad")
        requirements = PROVIDER_REQUIREMENTS[spec.optional_dependency]
        self.assertTrue(any(item.startswith("silero-vad==") for item in requirements))
        self.assertTrue(any(item.startswith("torch==") for item in requirements))

    def test_denoise_install_includes_audio_runtime(self):
        requirements = PROVIDER_REQUIREMENTS[get_spec("audio.denoise").optional_dependency]
        for package in ("DeepFilterNet", "torch", "torchaudio", "soundfile"):
            self.assertTrue(any(item.startswith(package + "==") for item in requirements))

    def test_document_install_includes_pipeline_extra(self):
        requirements = PROVIDER_REQUIREMENTS[get_spec("document.parse").optional_dependency]
        self.assertIn("mineru[pipeline]==3.4.5", requirements)
        self.assertIn("six==1.17.0", requirements)

    def test_retrieval_download_supports_configured_socks_proxy(self):
        requirements = PROVIDER_REQUIREMENTS[get_spec("vision.embed").optional_dependency]
        self.assertIn("socksio==1.0.0", requirements)
        self.assertIn("transformers==4.57.3", requirements)
        self.assertIn("sentencepiece==0.2.0", requirements)

    def test_pinned_requirement_probe_uses_import_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ProviderEnvironmentManager(Cache(Path(tmp) / "home"))
            manager.ensure("probe", [])
            self.assertTrue(manager.verify("probe", ["json==1.0", "pathlib>=1.0"]))
            self.assertFalse(manager.verify("probe", ["nonexistent_specialist_package==1.0"]))

    def test_discovery_does_not_create_runtime_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "absent"
            result = subprocess.run([sys.executable, "-m", "specialist", "--home", str(home), "capabilities", "ocr", "--compact"], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)[0]["capability"], "vision.ocr")
            self.assertFalse(home.exists())

    def test_batch_reuses_worker_and_stops_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "note.txt"
            source.write_text("Specialist OS")
            request = {"capability": "vision.ocr", "input": str(source), "options": {"no_cache": True}}
            path = root / "requests.json"
            path.write_text(json.dumps([request, request, {**request, "input": str(root / "missing")}, request]))
            command = [sys.executable, "-m", "specialist", "--home", str(root / "home"), "--backend", "fallback", "--isolate", "batch", str(path)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            values = json.loads(result.stdout)["results"]
            self.assertEqual(len(values), 3)
            self.assertTrue(values[0]["performance"]["cold_start"])
            self.assertFalse(values[1]["performance"]["cold_start"])
            self.assertFalse(values[1]["performance"]["cached"])
            continued = subprocess.run(command + ["--keep-going"], capture_output=True, text=True)
            self.assertEqual(len(json.loads(continued.stdout)["results"]), 4)

    def test_invalid_batch_validated_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.json"
            for value in ({}, [], [{"capability": "ocr", "input": "x", "options": []}], [{"capability": "missing", "input": "x"}]):
                path.write_text(json.dumps(value))
                with self.assertRaises((ValueError, KeyError)):
                    load_requests(path)

    def test_no_cache_bypasses_reads_and_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.txt"
            source.write_text("example")
            runtime = SpecialistRuntime(home=Path(tmp) / "home", backend="fallback")
            try:
                first = runtime.run("vision.ocr", source, {"no_cache": True})
                second = runtime.run("vision.ocr", source, {"no_cache": True})
                self.assertIsNone(first["error"])
                self.assertFalse(second["performance"]["cached"])
                self.assertFalse(second["provenance"]["cache"]["enabled"])
            finally:
                runtime.close()
