#!/usr/bin/env python3
"""Rehearse both Music workflows using only the public isolated real CLI."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from specialist.registry import get_spec
from specialist.schemas import validate_envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--only", choices=("music.parse_singing", "music.transcribe_full"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    input_sha256 = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if args.only and (args.output / "manifest.json").exists():
        previous = json.loads((args.output / "manifest.json").read_text())
        if previous.get("input_sha256") != input_sha256 or previous.get("artifact_home") != str(args.home.resolve()):
            raise ValueError("Cannot merge workflow evidence from different inputs or artifact homes")
        records = [r for r in previous["records"] if r["capability"] != args.only]
    for capability in ("music.parse_singing", "music.transcribe_full"):
        if args.only and capability != args.only:
            continue
        options = {"no_cache": True, "local_only": True}
        if capability == "music.transcribe_full":
            options["child_options"] = {"music.transcribe_multitrack": {"device": "mps" if sys.platform == "darwin" else "cpu"}}
        command = [str(Path(args.python).absolute()), "-m", "specialist", "--home", str(args.home.resolve()),
                   "--backend", "real", "--isolate", get_spec(capability).command, str(args.input.resolve()),
                   "--json", "--options", json.dumps(options)]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=4560)
        value = json.loads(completed.stdout)
        validate_envelope(value)
        filename = capability.replace(".", "-") + ".json"
        (args.output / filename).write_text(json.dumps(value, indent=2) + "\n")
        passed = completed.returncode == 0 and value["error"] is None and value["result"]["status"] == "ok"
        records.append({"capability": capability, "command": command, "result": filename, "status": "ok" if passed else "error"})
        print(f"{capability}: {records[-1]['status']}", flush=True)
    (args.output / "manifest.json").write_text(json.dumps({"records": records, "input_sha256": input_sha256, "artifact_home": str(args.home.resolve())}, indent=2) + "\n")
    return int(any(record["status"] != "ok" for record in records))


if __name__ == "__main__":
    raise SystemExit(main())
