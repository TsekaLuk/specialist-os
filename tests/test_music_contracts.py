"""Contract tests use data values, not simulated provider inference."""

import copy

import pytest

from specialist.music import validate_music_result
from specialist.schemas import ResultEnvelope, validate_envelope


URI = "artifact://" + "a" * 64


@pytest.mark.parametrize("capability,result", [
    ("music.analyze", {"duration": 2, "bpm": 120, "key": "C", "scale": "major", "beats": [0, 1], "loudness_lufs": -18}),
    ("music.separate", {"stems": {"vocals": URI, "instrumental": URI}}),
    ("music.fingerprint", {"duration": 2, "fingerprint": "AQAA"}),
    ("music.compare_recording", {"match": True, "similarity": 1, "threshold": .9, "metric": "chromaprint"}),
    ("music.transcribe_notes", {"notes": [{"pitch": 60, "start": 0, "end": 1, "velocity": .8}], "midi": URI}),
    ("music.transcribe_vocal", {"notes": [], "midi": URI}),
    ("music.transcribe_multitrack", {"tracks": [{"instrument": "piano", "notes": []}], "midi": URI}),
    ("music.generate", {"duration": 10, "audio": URI}),
])
def test_valid_music_wire_contracts(capability, result):
    before = copy.deepcopy(result)
    validate_music_result(capability, result)
    validate_envelope(ResultEnvelope(capability, "contract-test", "contract-test", {}, result).to_dict())
    assert result == before


@pytest.mark.parametrize("note", [
    {"pitch": True, "start": 0, "end": 1},
    {"pitch": 128, "start": 0, "end": 1},
    {"pitch": 60.5, "start": 0, "end": 1},
    {"pitch": 60, "start": -1, "end": 1},
    {"pitch": 60, "start": 1, "end": 1},
    {"pitch": 60, "start": 2, "end": 1},
    {"pitch": 60, "start": 0, "end": float("nan")},
    {"pitch": 60, "start": 0, "end": 1, "velocity": 127},
])
def test_invalid_note_events(note):
    with pytest.raises(ValueError):
        validate_music_result("music.transcribe_notes", {"notes": [note], "midi": URI})


@pytest.mark.parametrize("reference", ["output.mid", "artifact://../file", "artifact://midi", "https://example.com/a.mid", None])
def test_midi_requires_content_addressed_artifact(reference):
    with pytest.raises(ValueError):
        validate_music_result("music.transcribe_notes", {"notes": [], "midi": reference})


@pytest.mark.parametrize("beats", [[1, 0], [-1], [3], [float("inf")], [True]])
def test_invalid_beat_timeline(beats):
    with pytest.raises(ValueError):
        validate_music_result("music.analyze", {"duration": 2, "beats": beats})


def test_stems_are_not_symbolic_tracks():
    with pytest.raises(ValueError):
        validate_music_result("music.separate", {"stems": {"vocals": {"notes": []}}})


@pytest.mark.parametrize("capability,children", [
    ("music.parse_singing", ["audio.transcribe", "music.transcribe_vocal", "music.analyze"]),
    ("music.transcribe_full", ["music.analyze", "music.transcribe_multitrack", "music.separate"]),
])
def test_composite_failure_cannot_be_promoted_to_success(capability, children):
    result = {"status": "degraded", "children": {
        name: ResultEnvelope.failure(name, "unavailable", "unavailable", {}, "dependency_missing", "not installed").to_dict()
        for name in children
    }}
    validate_music_result(capability, result)
    result["status"] = "ok"
    with pytest.raises(ValueError, match="degraded"):
        validate_music_result(capability, result)
    result["status"] = "degraded"
    result["children"].pop(children[0])
    with pytest.raises(ValueError, match="required child"):
        validate_music_result(capability, result)


def test_composite_cannot_contain_itself():
    result = {"status": "ok", "children": {}}
    result["children"]["music.parse_singing"] = result
    with pytest.raises(ValueError):
        validate_music_result("music.parse_singing", result)


@pytest.mark.parametrize("options", [{"stems": ["bass"]}, {"stems": []}, {"stems": ["vocals", "vocals"]},
                                    {"profile": []}, {"profile": "unknown"}, {"device": "cuda"}])
def test_separator_rejects_unsupported_options_before_loading(options):
    from specialist.providers.music import AudioSeparatorProvider
    from specialist.providers.ipc import WorkerError

    with pytest.raises(WorkerError) as failure:
        AudioSeparatorProvider().infer("missing.wav", options, None)
    assert failure.value.code == "invalid_options"


def test_multitrack_rejects_unmapped_checkpoint_profile():
    from specialist.providers.music import MuScriptorProvider
    from specialist.providers.ipc import WorkerError

    with pytest.raises(WorkerError) as failure:
        MuScriptorProvider().infer("missing.wav", {"profile": "quality"}, None)
    assert failure.value.code == "invalid_options"


@pytest.mark.parametrize("options", [{"duration": True}, {"duration": float("nan")}, {"duration": 121},
                                    {"seed": -1}, {"seed": True}, {"instrumental": "yes"}, {"device": "metal"}])
def test_generation_rejects_invalid_options_before_loading(options):
    from specialist.providers.ace_step import AceStepProvider
    from specialist.providers.ipc import WorkerError

    with pytest.raises(WorkerError) as failure:
        AceStepProvider().infer("missing.txt", options, None)
    assert failure.value.code == "invalid_options"


def test_rosvot_portability_patch_fails_on_source_drift():
    from specialist.providers.rosvot import portable_source

    with pytest.raises(ValueError, match="portability contract"):
        portable_source("device = 'cuda'\n")


@pytest.mark.parametrize("name", ["../escape", "/absolute"])
def test_rosvot_archive_rejects_path_escape(tmp_path, name):
    import zipfile
    from specialist.providers.rosvot import extract_reviewed_zip

    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(name, b"unsafe")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_reviewed_zip(archive, tmp_path / "output")
