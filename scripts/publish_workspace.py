#!/usr/bin/env python3
"""Publish the built workspace and hash-matched media without removing evidence."""
import argparse
import hashlib
import json
import mimetypes
from pathlib import Path
import shutil


def publish(build: Path, destination: Path):
    manifest_path = destination / "demo.json"
    manifest = json.loads(manifest_path.read_text())
    assets = destination / "assets"
    media_by_hash = {}
    inputs_by_hash = {}
    for path in assets.iterdir():
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            inputs_by_hash[digest] = path.name
            if path.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".webm"}:
                media_by_hash[digest] = path.name
    for item in manifest["results"]:
        if item.get("preview") and not (assets / item["preview"]).is_file():
            raise ValueError(f"Missing preview for {item['capability']}: {item['preview']}")
        envelope = json.loads((assets / item["json"]).read_text())
        source = envelope.get("input") or {}
        filename = inputs_by_hash.get(source.get("sha256"))
        item["input_sample"] = {
            "name": filename or Path(source.get("path") or "Input sample").name,
            "src": filename,
            "sha256": source.get("sha256"),
            "mime": mimetypes.guess_type(filename)[0] if filename else None,
        }
        if not filename:
            for step in envelope.get("trace", []):
                text = (step.get("requested", {}).get("options") or {}).get("text")
                if isinstance(text, str) and hashlib.sha256(text.encode()).hexdigest() == source.get("sha256"):
                    item["input_sample"].update({"name": "Input text", "text": text, "mime": "text/plain"})
                    break
        result = envelope.get("result") or {}
        item["result_view"] = {
            "text": result.get("text") if isinstance(result.get("text"), str) else None,
            "segments": result.get("segments") if isinstance(result.get("segments"), list) else [],
        }
        references = envelope.get("artifacts", [])
        item["media"] = []
        for ref in references:
            mime = ref.get("mime", "")
            if not mime.startswith(("audio/", "video/")):
                continue
            digest = ref.get("sha256")
            if digest in media_by_hash:
                item["media"].append({"src": media_by_hash[digest], "mime": mime, "sha256": digest})
    shutil.copytree(build, destination, dirs_exist_ok=True)
    shutil.copyfile(build / "index.html", destination / "workspace.html")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"capabilities": len(manifest["results"]),
        "media": sum(len(item["media"]) for item in manifest["results"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    publish(args.build, args.destination)
