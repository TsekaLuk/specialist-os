"""Publication binds media to recorded artifacts, never guessed filenames."""
import json
from pathlib import Path
import shutil
import pytest

from scripts.publish_workspace import publish

ROOT = Path(__file__).resolve().parents[1]


def test_workspace_publishes_only_hash_matched_media(tmp_path):
    build, destination = tmp_path / 'dist', tmp_path / 'site'
    build.mkdir()
    (build / 'index.html').write_text('<div id="root"></div>')
    assets = destination / 'assets'
    assets.mkdir(parents=True)
    source = ROOT / 'docs/assets/e2e'
    shutil.copyfile(source / 'speech-synthesize.json', assets / 'speech-synthesize.json')
    shutil.copyfile(source / 'speech-synthesize.wav', assets / 'renamed.wav')
    (destination / 'demo.json').write_text(json.dumps({'results': [
        {'capability': 'speech.synthesize', 'json': 'speech-synthesize.json'}]}))
    publish(build, destination)
    records = json.loads((destination / 'demo.json').read_text())['results']
    assert records[0]['media'][0]['src'] == 'renamed.wav'
    assert (assets / 'speech-synthesize.json').exists()
    assert (destination / 'workspace.html').read_bytes() == (destination / 'index.html').read_bytes()
    (assets / 'renamed.wav').write_bytes(b'changed')
    publish(build, destination)
    assert json.loads((destination / 'demo.json').read_text())['results'][0]['media'] == []


def test_missing_preview_prevents_publication(tmp_path):
    build, destination = tmp_path / 'dist', tmp_path / 'site'
    build.mkdir()
    (build / 'index.html').write_text('new app')
    destination.mkdir()
    (destination / 'index.html').write_text('existing app')
    (destination / 'assets').mkdir()
    (destination / 'demo.json').write_text(json.dumps({'results': [
        {'capability': 'vision.detect', 'json': 'vision-detect.json', 'preview': 'missing.png'}]}))
    with pytest.raises(ValueError, match='Missing preview'):
        publish(build, destination)
    assert (destination / 'index.html').read_text() == 'existing app'
