import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from specialist.artifacts import ArtifactError, ArtifactStore
from specialist.benchmark import BenchmarkRecord, BenchmarkRegistry
from specialist.confidence import VerificationPolicy, agreement, combine
from specialist.cascade import SpecialistCascade
from specialist.graph import GraphError, SpecialistGraph
from specialist.node import ComputeNode, NodeRegistry, NodeScheduler
from specialist.observation import aggregate_confidence, build_observations
from specialist.policy import Policy
from specialist.provider_manifest import ProviderCatalog, ProviderManifest, ProviderManifestError
from specialist.packs import get_pack
from specialist.provider_sdk import ProviderAdapter
from specialist.studio import snapshot
from specialist.runtime import SpecialistRuntime


class AdvancedProtocolTests(unittest.TestCase):
    def test_artifact_resolution_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            store = ArtifactStore(root)
            ref = store.put_bytes(b"safe")
            path = store.resolve(ref)
            path.unlink()
            path.symlink_to(Path(temporary) / "outside")
            with self.assertRaises(ArtifactError):
                store.resolve(ref)

    def test_observations_are_deterministic_and_evidence_is_aggregated(self):
        source = {"type": "image", "path": "/tmp/input.png", "sha256": "a" * 64}
        result = {"items": [{"label": "bus", "bbox": [1, 2, 3, 4], "confidence": 0.9}]}
        first = build_observations("vision.detect", result, provider="yolo", model="yolo11n", source=source, runtime_version="1")
        second = build_observations("vision.detect", result, provider="yolo", model="yolo11n", source=source, runtime_version="1")
        self.assertEqual(first, second)
        self.assertEqual(aggregate_confidence(first), 0.9)
        self.assertEqual(first[0]["provenance"]["source"], source)

    def test_policy_explicit_remote_option_is_not_contradictory(self):
        policy = Policy.from_mapping({"policy": {"allow_remote": False}})
        self.assertFalse(policy.resolve("vision.ocr", {"allow_remote": True})["local_only"])

    def test_manifest_catalog_is_metadata_only(self):
        value = {"provider": "community-ocr", "version": "1.0.0", "capability": ["vision.ocr"], "runtime": {"type": "python"}, "models": {}, "metrics": {}, "license": {"code": "MIT", "weights": "MIT"}, "platform": {"macos_arm64": True}}
        manifest = ProviderManifest.from_dict(value)
        with tempfile.TemporaryDirectory() as temporary:
            catalog = ProviderCatalog(Path(temporary) / "providers")
            installed = catalog.install(manifest)
            self.assertEqual(installed.provider, "community-ocr")
            self.assertEqual(catalog.get("community-ocr").version, "1.0.0")
            self.assertEqual(len(catalog.list()), 1)

    def test_manifest_rejects_missing_contract(self):
        with self.assertRaises(ProviderManifestError):
            ProviderManifest.from_dict({"provider": "bad"})

    def test_graph_executes_dependency_levels(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "note.txt"
            path.write_text("graph", encoding="utf-8")
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="fallback")
            graph = SpecialistGraph("ocr-and-transcribe").add("ocr", "vision.ocr").add("transcript", "audio.transcribe", depends_on=["ocr"])
            value = runtime.run_graph(graph, path)
            self.assertEqual(value["status"], "completed")
            self.assertEqual(set(value["nodes"]), {"ocr", "transcript"})
            with self.assertRaises(GraphError):
                SpecialistGraph().add("a", "vision.ocr", depends_on=["b"]).add("b", "vision.ocr", depends_on=["a"]).execute(runtime, path)
            runtime.close()

    def test_session_push_poll_and_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="fallback")
            session = runtime.open_session("vision.ocr")
            event = session.push(b"stream text")
            self.assertEqual(event["event"], "result")
            self.assertEqual(session.poll()[0]["sequence"], 1)
            self.assertEqual(session.close()["event"], "closed")
            runtime.close()

    def test_node_registry_scheduler_and_benchmark(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = ComputeNode.create("local", capabilities=("vision.ocr",), memory_mb=2048)
            registry = NodeRegistry(root / "nodes")
            registry.register(node)
            decision = NodeScheduler().select("vision.ocr", registry.list(), local_only=True)
            self.assertEqual(decision["selected"]["node_id"], node.node_id)
            benchmarks = BenchmarkRegistry(root / "benchmarks.json")
            item = benchmarks.record(BenchmarkRecord("vision.ocr", "paddleocr", "model", {"os": "x", "architecture": "y", "cpu": "z"}, 10.0))
            self.assertEqual(benchmarks.best("vision.ocr")["latency_ms"], 10.0)

    def test_confidence_and_verification(self):
        self.assertEqual(agreement(["same", "same", "other"]), 0.5)
        self.assertGreater(combine(0.8, provider_agreement=1.0), 0.8)
        self.assertTrue(VerificationPolicy("confidence_threshold", 0.9).should_verify(0.8))

    def test_pack_sdk_and_studio_snapshot(self):
        self.assertIn("vision.ocr", get_pack("vision-core").capabilities)
        manifest = ProviderManifest.from_dict({"provider": "provider", "version": "1", "capability": ["vision.ocr"], "runtime": {}, "models": {}, "metrics": {}, "license": {}, "platform": {}})
        adapter = type("OCRProvider", (ProviderAdapter,), {"name": "provider", "capability": "vision.ocr"})
        self.assertIs(adapter.validate_manifest(manifest), manifest)
        with tempfile.TemporaryDirectory() as temporary:
            runtime = SpecialistRuntime(home=Path(temporary) / "home", backend="fallback")
            value = snapshot(runtime)
            self.assertIn("capabilities", value)
            self.assertIn("models", value)
            runtime.close()

    def test_cascade_records_escalation_trace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "frame.png"
            path.write_bytes(b"not-an-image")
            runtime = SpecialistRuntime(home=root / "home", backend="fallback")
            cascade = SpecialistCascade(name="quality-escalation").add("vision.ocr", min_confidence=0.99).add("audio.transcribe", min_confidence=0.0)
            result = runtime.run_cascade(cascade, path)
            self.assertEqual(result["trace"][-1]["stage"], "cascade")
            self.assertEqual(len(result["trace"][-1]["steps"]), 2)
            runtime.close()


if __name__ == "__main__":
    unittest.main()
