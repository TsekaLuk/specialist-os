"""Installation and credential boundaries, without simulated inference."""
import urllib.request

import pytest

from specialist.models import model_request
from specialist.music import music_classification
from specialist.registry import BUNDLES, registry_snapshot


def test_hf_auth_is_not_redirected(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test_non_secret_value")
    request = model_request("https://huggingface.co/a/b/resolve/main/model", {})
    assert request.get_header("Authorization") == "Bearer test_non_secret_value"
    redirected = urllib.request.HTTPRedirectHandler().redirect_request(
        request, None, 302, "Found", {}, "https://cdn.example/model")
    assert redirected.get_header("Authorization") is None


@pytest.mark.parametrize("url", ["http://huggingface.co/model", "https://huggingface.co.example/model", "https://example.com/model"])
def test_credentials_never_sent_to_other_origins(monkeypatch, url):
    monkeypatch.setenv("HF_TOKEN", "test_non_secret_value")
    assert model_request(url, {}).get_header("Authorization") is None


def test_hf_token_file(monkeypatch, tmp_path):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    path = tmp_path / "token"
    path.write_text("test_local_credential\n")
    monkeypatch.setenv("HF_TOKEN_PATH", str(path))
    assert model_request("https://huggingface.co/model", {}).get_header("Authorization") == "Bearer test_local_credential"


def test_music_pack_boundaries_and_discovery():
    assert "music.generate" not in BUNDLES["music"]
    assert "music.transcribe_vocal" not in BUNDLES["music"]
    assert BUNDLES["music-generation"] == ["music.generate"]
    assert BUNDLES["music-experimental"] == ["music.transcribe_vocal"]
    assert not any(name.startswith("music.") for name in BUNDLES["core"])
    assert music_classification("music.generate") == {"maturity": "EXPERIMENTAL", "execution_class": "heavy_generative"}
    for row in registry_snapshot():
        if row["capability"].startswith("music."):
            assert row["output_schema"]["required"]


@pytest.mark.parametrize("options", [{"bpm": True}, {"bpm": 301}, {"key": "unknown"}, {"provider_options": {"shell": "unsafe"}}])
def test_generation_controls_fail_before_inference(options):
    from specialist.providers.ace_step import AceStepProvider
    from specialist.providers.ipc import WorkerError
    with pytest.raises(WorkerError) as failure:
        AceStepProvider().infer("missing.txt", options, None)
    assert failure.value.code == "invalid_options"


def test_release_requires_real_artifacts_but_not_native_weights(monkeypatch):
    from scripts import release_check
    assert release_check.check_registry(True) == []
    registry = release_check.load_registry()
    native = next(row for row in registry['capabilities'] if row['name'] == 'music.analyze')
    native['models'][0]['artifact']['url'] = 'https://example.com/model'
    native['models'][0]['artifact']['sha256'] = 'a' * 64
    monkeypatch.setattr(release_check, 'load_registry', lambda: registry)
    assert any('native capabilities cannot' in error for error in release_check.check_registry(True))


def test_installed_music_still_validates_requested_model(tmp_path):
    from specialist.runtime import SpecialistRuntime
    runtime = SpecialistRuntime(home=tmp_path, backend='real', isolate=True)
    try:
        runtime.cache.mark_installed('music.analyze', 'essentia', 'essentia-2.1b6.dev1389')
        with pytest.raises(ValueError, match='not registered'):
            runtime.install('music.analyze', model='unknown-model')
    finally:
        runtime.close()


def test_generation_pack_defers_weights_without_ready_marker(tmp_path):
    from specialist.runtime import SpecialistRuntime
    runtime = SpecialistRuntime(home=tmp_path, backend='real', isolate=True)
    try:
        records = runtime.install_pack('music-generation', with_dependencies=False)
        assert len(records) == 1
        assert records[0]['downloaded'] is False
        assert records[0]['model_state'] == 'on_demand'
        assert runtime.cache.installation('music.generate') is None
    finally:
        runtime.close()
