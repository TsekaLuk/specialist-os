#!/usr/bin/env python3
"""Run available Music adapters on a licensed recording through the public CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specialist.cache import Cache
from specialist.models import ModelManager
from specialist.schemas import validate_envelope
from specialist.registry import get_spec


FIXTURE = {
    "title": "Vibe Ace", "author": "Kevin MacLeod", "category": "jazz",
    "license": "CC-BY-3.0", "license_url": "https://creativecommons.org/licenses/by/3.0/",
    "source": "https://freemusicarchive.org/music/Kevin_MacLeod/Jazz_Sampler/Vibe_Ace",
    "url": "https://librosa.org/data/audio/Kevin_MacLeod_-_Vibe_Ace.hq.ogg",
    "sha256": "73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Interpreter with Essentia installed")
    parser.add_argument("--notes-python", help="Optional isolated Basic Pitch interpreter")
    parser.add_argument("--separation-python", help="Optional audio-separator interpreter with a verified installed model")
    parser.add_argument("--multitrack-python", help="Optional MuScriptor interpreter with an authorized verified installed bundle")
    parser.add_argument("--vocal-python", help="Optional ROSVOT interpreter with verified installed source and checkpoints")
    parser.add_argument("--only", action="append", help="Run only selected capability names; preserve other records from the same fixture")
    parser.add_argument("--fixture", type=Path, help="Licensed fixture descriptor JSON with url and sha256")
    parser.add_argument("--home", type=Path, help="Reuse provisioned model home")
    parser.add_argument("--output", type=Path, default=ROOT / "output/music-rehearsal")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    descriptor = json.loads(args.fixture.read_text()) if args.fixture else FIXTURE
    filename = descriptor.get("filename", "vibe-ace.ogg")
    if Path(filename).name != filename:
        raise ValueError("Fixture filename must be a basename")
    fixture = output / filename
    cache = Cache(args.home.resolve() if args.home else output / "home")
    if not fixture.exists() or hashlib.sha256(fixture.read_bytes()).hexdigest() != descriptor["sha256"]:
        ModelManager(cache).download(descriptor["url"], fixture, descriptor["sha256"])
    records = []
    if args.only and (output / "manifest.json").exists():
        previous = json.loads((output / "manifest.json").read_text())
        if previous["fixture"]["sha256"] != descriptor["sha256"]:
            raise ValueError("Cannot merge evidence from different fixtures")
        records = [r for r in previous["records"] if r["capability"] not in args.only]
    cases = [
        ("music.analyze", {}),
        ("music.analyze", {"features": ["chroma", "mfcc", "spectral", "onsets", "tuning"]}),
        ("music.fingerprint", {}),
        ("music.compare_recording", {"other_input": str(fixture)}),
    ]
    if args.notes_python:
        cases.append(("music.transcribe_notes", {}))
    if args.separation_python:
        cases.append(("music.separate", {"timeout_seconds": 900}))
    if args.multitrack_python:
        cases.append(("music.transcribe_multitrack", {"device": "mps" if sys.platform == "darwin" else "cpu", "timeout_seconds": 900}))
    if args.vocal_python:
        cases.append(("music.transcribe_vocal", {"timeout_seconds": 900}))
    if args.only:
        if set(args.only) - {name for name, _ in cases}:
            raise ValueError("Selected capability needs its provider interpreter flag")
        cases = [(name, opts) for name, opts in cases if name in args.only]
    for capability, options in cases:
        interpreter = {"music.transcribe_notes": args.notes_python,
                       "music.separate": args.separation_python,
                       "music.transcribe_vocal": args.vocal_python,
                       "music.transcribe_multitrack": args.multitrack_python}.get(capability, args.python)
        command = [str(Path(interpreter).absolute()), "-m", "specialist", "--home", str(cache.home),
                   "--backend", "real", "--isolate", get_spec(capability).command, str(fixture), "--json",
                   "--options", json.dumps({"no_cache": True, **options})]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=960)
        try:
            envelope = json.loads(completed.stdout)
            validate_envelope(envelope)
        except (ValueError, TypeError) as exc:
            envelope = {"error": {"code": "invalid_cli_output", "message": str(exc)}, "stderr": completed.stderr[-2000:]}
        option_id = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()[:8]
        name = f"{capability.replace('.', '-')}-{option_id}.json"
        (output / name).write_text(json.dumps(envelope, indent=2, allow_nan=False) + "\n")
        records.append({"capability": capability, "command": command, "result": name,
                        "status": "ok" if completed.returncode == 0 and envelope.get("error") is None else "error"})
        print(f"{capability}: {records[-1]['status']}", flush=True)
    (output / "manifest.json").write_text(json.dumps({"fixture": descriptor, "artifact_home": str(cache.home), "records": records}, indent=2) + "\n")
    return int(any(row["status"] != "ok" for row in records))


if __name__ == "__main__":
    raise SystemExit(main())
