#!/usr/bin/env python3
"""Publish the built workspace and hash-matched media without removing evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def publish(build: Path, destination: Path):
    manifest_path = destination / "demo.json"
    manifest = json.loads(manifest_path.read_text())
    assets = destination / "assets"
    media_by_hash = {}
    for path in assets.iterdir():
        if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".mp4", ".webm"}:
            media_by_hash[hashlib.sha256(path.read_bytes()).hexdigest()] = path.name
    for item in manifest["results"]:
        envelope = json.loads((assets / item["json"]).read_text())
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
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"capabilities": len(manifest["results"]),
        "media": sum(len(item["media"]) for item in manifest["results"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    publish(args.build, args.destination)
