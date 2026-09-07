#!/usr/bin/env python3
"""Run reproducible music generation using the public real, isolated CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from specialist.schemas import validate_envelope
from specialist.registry import get_spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", type=Path)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu")
    parser.add_argument("--bpm", type=int)
    parser.add_argument("--key")
    parser.add_argument("--reference-audio", type=Path)
    args = parser.parse_args()
    options = {"no_cache": True, "local_only": True, "device": args.device,
               "duration": 15, "seed": 42, "timeout_seconds": 1800}
    inputs = {"prompt": {"path": str(args.prompt.resolve()),
                         "sha256": hashlib.sha256(args.prompt.read_bytes()).hexdigest()}}
    for name in ("bpm", "key"):
        if getattr(args, name) is not None:
            options[name] = getattr(args, name)
    if args.reference_audio:
        options["reference_audio"] = str(args.reference_audio.resolve())
        inputs["reference_audio"] = {"path": options["reference_audio"],
            "sha256": hashlib.sha256(args.reference_audio.read_bytes()).hexdigest()}
    args.output.mkdir(parents=True, exist_ok=True)
    command = [str(Path(args.python).absolute()), "-m", "specialist", "--home", str(args.home.resolve()),
               "--backend", "real", "--isolate", get_spec("music.generate").command,
               str(args.prompt.resolve()), "--json", "--options", json.dumps(options)]
    print("music.generate: running", flush=True)
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=1860)
    (args.output / "stderr.log").write_text(run.stderr)
    value = json.loads(run.stdout)
    validate_envelope(value)
    filename = "music-generate.json"
    (args.output / filename).write_text(json.dumps(value, indent=2) + "\n")
    (args.output / "manifest.json").write_text(json.dumps({"command": command,
        "result": filename, "inputs": inputs, "artifact_home": str(args.home.resolve())}, indent=2) + "\n")
    passed = run.returncode == 0 and value["error"] is None
    print(json.dumps({"status": "ok" if passed else "error", "error": value["error"], "performance": value["performance"]}))
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())
