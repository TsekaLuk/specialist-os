"""Opt-in end-to-end checks against a running Fish Speech S2 server.

Set ``SPECIALIST_RUN_FISH_AUDIO_E2E=1`` and point
``SPECIALIST_FISH_AUDIO_URL`` at an operator-managed server. The test consumes
the server's actual response and verifies the public Artifact contract.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from specialist.runtime import SpecialistRuntime


RUN_REAL = os.environ.get("SPECIALIST_RUN_FISH_AUDIO_E2E") == "1"
ENDPOINT = os.environ.get("SPECIALIST_FISH_AUDIO_URL")


@unittest.skipUnless(
    RUN_REAL and ENDPOINT,
    "set SPECIALIST_RUN_FISH_AUDIO_E2E=1 and SPECIALIST_FISH_AUDIO_URL to run Fish Audio E2E",
)
class RealFishAudioE2ETests(unittest.TestCase):
    def test_real_server_synthesizes_and_persists_audio_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            text = root / "speech.txt"
            text.write_text("Specialist OS production voice check.", encoding="utf-8")
            runtime = SpecialistRuntime(home=root / "home", backend="real", isolate=True)
            try:
                result = runtime.run(
                    "speech.synthesize",
                    text,
                    {
                        "text": text.read_text(encoding="utf-8"),
                        "provider": "fish_audio",
                        "profile": "quality",
                        "allow_remote": True,
                        "local_only": False,
                    },
                )
                self.assertIsNone(result["error"], result)
                audio = result["result"]["audio"]
                self.assertTrue(audio["artifact"].startswith("artifact://"))
                self.assertTrue(audio["mime"].startswith("audio/"))
                artifact = runtime.artifacts.resolve(audio["artifact"])
                self.assertGreater(artifact.stat().st_size, 0)
                self.assertEqual(result["provider"], "fish_audio")
                self.assertEqual(result["provenance"]["provider"], "fish_audio")
            finally:
                runtime.close()

    def test_real_server_clone_voice_uses_explicit_reference(self):
        reference_value = os.environ.get("SPECIALIST_FISH_AUDIO_REFERENCE")
        if not reference_value:
            self.skipTest("set SPECIALIST_FISH_AUDIO_REFERENCE to run real voice cloning")
        reference = Path(reference_value).expanduser()
        self.assertTrue(reference.is_file(), reference)
        parsed = urlsplit(ENDPOINT or "")
        allow_remote = parsed.hostname in {"127.0.0.1", "localhost", "::1"} or os.environ.get("SPECIALIST_FISH_AUDIO_ALLOW_REMOTE") == "1"
        if not allow_remote:
            self.skipTest("set SPECIALIST_FISH_AUDIO_ALLOW_REMOTE=1 for a remote reference-audio test")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = SpecialistRuntime(home=root / "home", backend="real", isolate=True)
            try:
                result = runtime.run(
                    "speech.clone_voice",
                    reference,
                    {
                        "text": "Specialist OS voice cloning check.",
                        "reference_audio": str(reference),
                        "provider": "fish_audio",
                        "allow_remote": allow_remote,
                        "local_only": not allow_remote,
                    },
                )
                self.assertIsNone(result["error"], result)
                self.assertEqual(result["provider"], "fish_audio")
                self.assertTrue(result["result"]["audio"]["artifact"].startswith("artifact://"))
                self.assertTrue(result["result"].get("voice"))
            finally:
                runtime.close()


if __name__ == "__main__":
    unittest.main()
