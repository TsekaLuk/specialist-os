"""Rerun selected gallery CLI requests, retaining previous attempt evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import generate_readme_gallery as gallery_module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("capabilities", nargs="+")
    parser.add_argument("--python", required=True)
    parser.add_argument("--home", type=Path, default=Path.home() / ".specialist")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--options", type=json.loads, default={}, help="Option overrides for the selected requests")
    parser.add_argument("--request-file", type=Path, help="Use input/options from a recorded CLI batch request")
    args = parser.parse_args()
    assets = args.assets.resolve()
    path = assets / "capability-gallery.json"
    manifest = json.loads(path.read_text())
    overrides = {item["capability"]: item for item in json.loads(args.request_file.read_text())} if args.request_file else {}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    history = assets / "attempts" / stamp
    history.mkdir(parents=True)
    shutil.copyfile(path, history / path.name)
    gallery_module.ASSETS = assets
    gallery = gallery_module.Gallery(args.python, args.home.resolve(), "real", False, args.timeout)
    for name in args.capabilities:
        record = manifest["records"][name]
        command = record["command"]
        position = command.index("--isolate") + 1
        operation = command[position]
        source = command[position + (2 if operation == "clone-voice" else 1)]
        options = json.loads(command[command.index("--options") + 1])
        options.update(args.options)
        if name in overrides:
            source = overrides[name]["input"]
            options = {**overrides[name].get("options", {}), **args.options}
        shutil.copyfile(assets / record["json"], history / record["json"])
        result = gallery.run(name, operation, source, options, title=record["title"])
        manifest["records"][name] = gallery.records[name]
        audio = (result.get("result") or {}).get("audio") or {}
        if not result.get("error") and audio.get("artifact"):
            suffix = {"audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/flac": ".flac"}[audio["mime"]]
            filename = gallery_module._slug(name) + suffix
            shutil.copyfile(gallery.artifact_path(audio["artifact"]), assets / filename)
            manifest["audio"][name] = filename
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"capability": name, "status": gallery.records[name]["status"], "error": result.get("error")}), flush=True)
    return int(any(record["status"] != "ok" for record in gallery.records.values()))


if __name__ == "__main__":
    raise SystemExit(main())
