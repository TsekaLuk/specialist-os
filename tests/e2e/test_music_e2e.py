"""Real native Chromaprint through the isolated public CLI, no provider doubles."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from specialist.artifacts import ArtifactStore
from specialist.schemas import validate_envelope


pytestmark = pytest.mark.skipif(
    os.environ.get("SPECIALIST_RUN_MUSIC_E2E") != "1",
    reason="set SPECIALIST_RUN_MUSIC_E2E=1 for native Music CLI checks",
)
ROOT = Path(__file__).resolve().parents[2]


def invoke(home, capability, source, **options):
    completed = subprocess.run(
        [sys.executable, "-m", "specialist", "--home", str(home), "--backend", "real",
         "--isolate", capability, str(source), "--json", "--options", json.dumps(options)],
        cwd=ROOT, capture_output=True, text=True, timeout=240,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["error"] is None, result
    validate_envelope(result)
    assert result["provider"] == "chromaprint"
    assert result["model"] == "chromaprint-1.6.1"
    return result


def test_fingerprint_repeatability_and_recording_comparison(tmp_path):
    assert shutil.which("fpcalc"), "install Chromaprint 1.6.1"
    source = Path(os.environ.get("SPECIALIST_MUSIC_FIXTURE", str(ROOT / "docs/assets/e2e/meeting-two-speaker.wav")))
    assert source.is_file()
    first = invoke(tmp_path, "music-fingerprint", source, no_cache=True)
    second = invoke(tmp_path, "music-fingerprint", source, no_cache=True)
    assert first["result"]["fingerprint"] == second["result"]["fingerprint"]
    assert first["input"]["sha256"] == second["input"]["sha256"]
    assert not second["performance"]["cached"]
    artifact = ArtifactStore(tmp_path / "artifacts").resolve(first["artifacts"][0])
    assert json.loads(artifact.read_text())["fingerprint"] == first["result"]["fingerprint"]
    comparison = invoke(tmp_path, "music-compare-recording", source, other_input=str(source), no_cache=True)
    assert comparison["result"]["match"] is True
    assert comparison["result"]["similarity"] == 1


def test_comparison_cache_tracks_secondary_file_contents(tmp_path):
    source = ROOT / "docs/assets/e2e/meeting-two-speaker.wav"
    secondary = tmp_path / "secondary.wav"
    shutil.copyfile(source, secondary)
    first = invoke(tmp_path, "music-compare-recording", source, other_input=str(secondary))
    shutil.copyfile(ROOT / "docs/assets/e2e/speech-synthesize.wav", secondary)
    second = invoke(tmp_path, "music-compare-recording", source, other_input=str(secondary))
    assert not second["performance"]["cached"]
    assert first["result"]["other_input_sha256"] != second["result"]["other_input_sha256"]


def test_missing_experimental_provider_does_not_break_stable_music(tmp_path):
    from specialist.runtime import SpecialistRuntime
    runtime = SpecialistRuntime(home=tmp_path, backend='real', isolate=True)
    source = ROOT / 'docs/assets/e2e/meeting-two-speaker.wav'
    try:
        failed = runtime.run('music.transcribe_vocal', str(source), options={'no_cache': True})
        assert failed['error'] is not None
        stable = runtime.run('music.fingerprint', str(source), options={'no_cache': True})
        validate_envelope(stable)
        assert stable['error'] is None
        assert stable['provider'] == 'chromaprint'
        assert stable['result']['fingerprint']
    finally:
        runtime.close()
