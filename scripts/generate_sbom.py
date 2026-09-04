"""Generate a dependency and model provenance SBOM for a release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone
import uuid


ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]$", text, re.MULTILINE)
    return match.group(1) if match else "unknown"


def packages() -> list[dict]:
    try:
        completed = subprocess.run(["python", "-m", "pip", "list", "--format=json"], capture_output=True, text=True, check=True)
        return [{"name": item["name"], "version": item["version"]} for item in json.loads(completed.stdout)]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        return []


def models() -> list[dict]:
    registry = json.loads((ROOT / "registry" / "models.yaml").read_text(encoding="utf-8"))
    components = []
    for capability in registry["capabilities"]:
        for model in capability["models"]:
            artifact = model.get("artifact") or {}
            components.append({
                "type": "machine-learning-model",
                "bom-ref": f"model:{capability['name']}:{model['id']}",
                "name": model["id"],
                "group": capability["provider"],
                "version": model["id"],
                "licenses": [{"license": {"id": capability["license"]["weights"]}}],
                "externalReferences": ([{"type": "distribution", "url": artifact["url"]}] if artifact.get("url") else []) + ([{"type": "vcs", "url": capability["source_url"]}] if capability.get("source_url") else []),
                "hashes": ([{"alg": "SHA-256", "content": artifact["sha256"]}] if artifact.get("sha256") else []),
                "properties": [{"name": "specialist.capability", "value": capability["name"]}, {"name": "specialist.recommended", "value": str(bool(model.get("recommended"))).lower()}],
            })
    return components


def build() -> dict:
    components = [{"type": "library", "bom-ref": f"pkg:pypi/specialist-os@{project_version()}", "name": "specialist-os", "version": project_version(), "licenses": [{"license": {"id": "MIT"}}]}]
    components.extend({"type": "library", "bom-ref": f"pkg:pypi/{item['name'].lower()}@{item['version']}", **item} for item in packages())
    components.extend(models())
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/TsekaLuk/specialist-os/releases/{project_version()}")
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial}", "version": 1, "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(), "component": {"name": "specialist-os", "version": project_version()}}, "components": components}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-o", "--output", type=Path, default=ROOT / "dist" / "sbom.cdx.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
