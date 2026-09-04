import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from specialist.artifacts import ArtifactStore
from specialist.providers.expansion import CompositeProvider
from specialist.runtime import SpecialistRuntime


class CapabilityExpansionTests(unittest.TestCase):
    def test_transcribe_video_resolves_flat_audio_artifacts_between_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "meeting.mp4"
            extracted_audio = root / "meeting-extracted.wav"
            denoised_audio = root / "meeting-denoised.wav"
            video.write_bytes(b"video")
            extracted_audio.write_bytes(b"extracted wav")
            denoised_audio.write_bytes(b"denoised wav")
            artifacts = ArtifactStore(root / "artifacts")
            extracted_ref = artifacts.put_file(extracted_audio, mime="audio/wav")
            denoised_ref = artifacts.put_file(denoised_audio, mime="audio/wav")
            extracted_path = artifacts.resolve(extracted_ref)
            denoised_path = artifacts.resolve(denoised_ref)

            class RecordingRuntime:
                def __init__(self):
                    self.artifacts = artifacts
                    self.calls = []

                def run(self, capability, input_path, options):
                    self.calls.append((capability, Path(input_path), options))
                    result = {
                        "media.audio.extract": {"audio_path": extracted_ref.uri},
                        "audio.denoise": {"audio_path": denoised_ref.uri},
                        "audio.transcribe": {"text": "A real transcript.", "segments": []},
                    }[capability]
                    return {
                        "capability": capability,
                        "provider": "recording",
                        "model": "test",
                        "result": result,
                        "artifacts": [],
                        "provenance": {},
                        "warnings": [],
                        "error": None,
                    }

            runtime = RecordingRuntime()
            provider = CompositeProvider("media.transcribe_video")
            provider.runtime = runtime
            result, warnings = provider.infer(video, {}, None)

            self.assertEqual(runtime.calls[0][0:2], ("media.audio.extract", video))
            self.assertEqual(runtime.calls[1][0:2], ("audio.denoise", extracted_path))
            self.assertEqual(runtime.calls[2][0:2], ("audio.transcribe", denoised_path))
            self.assertEqual(result["text"], "A real transcript.")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(warnings, [])

    def test_measure_defaults_to_relative_depth_without_claiming_metric_estimate(self):
        class RecordingRuntime:
            def __init__(self):
                self.calls = []

            def run(self, capability, input_path, options):
                self.calls.append((capability, options))
                if capability == "vision.detect":
                    result = {"items": []}
                elif capability == "vision.depth":
                    result = {"mode": options["mode"], "unit": None, "estimated": False}
                else:
                    result = {"distance": 5.0, "dimensions": 2, "deterministic": True}
                return {
                    "capability": capability,
                    "provider": "recording",
                    "model": "test",
                    "result": result,
                    "artifacts": [],
                    "provenance": {},
                    "warnings": [],
                    "error": None,
                }

        runtime = RecordingRuntime()
        provider = CompositeProvider("vision.measure")
        provider.runtime = runtime
        result, warnings = provider.infer(Path("scene.png"), {"points": [[0, 0], [3, 4]]}, None)

        self.assertEqual(runtime.calls[1], ("vision.depth", {"points": [[0, 0], [3, 4]], "mode": "relative"}))
        self.assertEqual(result["mode"], "relative")
        self.assertFalse(result["estimated"])
        self.assertEqual(result["measurement"]["distance"], 5.0)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(warnings, [])

    def test_fallback_retrieval_supports_artifact_inputs_and_ranked_corpus(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            query = root / "query.bin"
            same = root / "same.bin"
            other = root / "other.bin"
            query.write_bytes(b"query image bytes")
            same.write_bytes(query.read_bytes())
            other.write_bytes(b"a different image")
            runtime = SpecialistRuntime(home=root / "home", backend="fallback")
            try:
                artifact = runtime.artifacts.put_file(same, mime="image/png")
                similarity = runtime.run("vision.similarity", query, {"other_input": artifact.uri})
                self.assertIsNone(similarity["error"])
                self.assertGreater(similarity["result"]["score"], 0.99)
                text_similarity = runtime.run("vision.similarity", query, {"text": "a different semantic query"})
                self.assertIsNone(text_similarity["error"])
                self.assertLess(text_similarity["result"]["score"], 0.99)

                search = runtime.run("vision.search", query, {"corpus": [str(other), str(same)], "top_k": 2})
                self.assertIsNone(search["error"])
                self.assertEqual(search["result"]["results"][0]["artifact"], str(same))
                self.assertEqual(len(search["result"]["results"]), 2)

                invalid = runtime.run("vision.similarity", query, {"other_input": "artifact://" + "0" * 64})
                self.assertEqual(invalid["error"]["code"], "invalid_artifact")
            finally:
                runtime.close()

    def test_face_artifact_uri_is_resolved_and_sensitive_results_are_not_cached(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.bin"
            second = root / "second.bin"
            first.write_bytes(b"face input")
            second.write_bytes(b"face reference")
            runtime = SpecialistRuntime(home=root / "home", backend="fallback")
            try:
                reference = runtime.artifacts.put_file(second, mime="image/png")
                first_result = runtime.run("identity.face.verify", first, {"other_input": reference.uri})
                second_result = runtime.run("identity.face.verify", first, {"other_input": reference.uri})
                for result in (first_result, second_result):
                    self.assertIsNone(result["error"])
                    self.assertIsNone(result["result"]["match"])
                    self.assertEqual(result["result"]["status"], "unavailable")
                    self.assertFalse(result["performance"]["cached"])
                self.assertFalse(list(runtime.cache.logs.glob("*")))
            finally:
                runtime.close()

    def test_opencv_operators_validate_options_before_loading_optional_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "image.ppm"
            image.write_text("P3\n1 1\n255\n255 255 255\n", encoding="ascii")
            runtime = SpecialistRuntime(home=root / "home", backend="fallback")
            try:
                features = runtime.run("vision.geometry.match_features", image, {"image_b": str(image), "ratio": 2.0})
                self.assertEqual(features["error"]["code"], "invalid_geometry")
                pnp = runtime.run(
                    "vision.geometry.solve_pnp",
                    image,
                    {
                        "object_points": [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                        "image_points": [[0, 0], [1, 0], [1, 1], [0, 1]],
                        "camera_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
                        "distortion": [0, 0, 0],
                    },
                )
                self.assertEqual(pnp["error"]["code"], "invalid_geometry")
                warp = runtime.run("vision.transform.warp", image, {"matrix": [[1, 0], [0, 1]]})
                self.assertEqual(warp["error"]["code"], "invalid_options")
            finally:
                runtime.close()

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_real_media_frame_artifacts_are_promoted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "fixture.mp4"
            completed = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=32x32:rate=2:duration=1", "-pix_fmt", "yuv420p", str(video)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            runtime = SpecialistRuntime(home=root / "home", backend="fallback")
            try:
                probe = runtime.run("media.probe", video)
                self.assertIsNone(probe["error"])
                self.assertEqual(probe["result"]["video"]["width"], 32)
                frames = runtime.run("media.video.extract_frames", video, {"fps": 2})
                self.assertIsNone(frames["error"])
                values = frames["result"]["frames"]
                self.assertGreaterEqual(len(values), 1)
                self.assertTrue(all(value.startswith("artifact://") for value in values))
                self.assertTrue(all(item["mime"] == "image/png" for item in frames["artifacts"]))
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
