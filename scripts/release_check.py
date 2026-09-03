"""Validate release metadata before publishing an artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]


def load_registry():
    path = ROOT / "registry" / "models.yaml"
    return json.loads(path.read_text(encoding="utf-8"))


def project_version():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]\s*$", pyproject, re.MULTILINE)
    if not match:
        raise ValueError("pyproject.toml does not declare project.version")
    return match.group(1)


def check_registry(require_artifacts: bool) -> list[str]:
    payload = load_registry()
    failures = []
    capabilities = payload.get("capabilities", [])
    if payload.get("schema_version") != 1 or not isinstance(capabilities, list):
        return ["registry must contain schema_version=1 and a capabilities array"]
    names = set()
    for capability in capabilities:
        name = capability.get("name")
        if not isinstance(name, str) or not name or name in names:
            failures.append(f"invalid or duplicate capability name: {name!r}")
        names.add(name)
        models = capability.get("models") or []
        if sum(bool(model.get("recommended")) for model in models) != 1:
            failures.append(f"{name}: exactly one recommended model is required")
        for model in models:
            artifact = model.get("artifact") or {}
            url = artifact.get("url")
            digest = artifact.get("sha256")
            if (url is None) != (digest is None):
                failures.append(f"{name}/{model.get('id')}: artifact URL and SHA256 must be paired")
            if url is not None and (not isinstance(url, str) or not url.startswith(("https://", "http://", "file://"))):
                failures.append(f"{name}/{model.get('id')}: artifact URL must use https://, http:// or file://")
            if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
                failures.append(f"{name}/{model.get('id')}: artifact SHA256 must be 64 hexadecimal characters")
            if require_artifacts and (url is None or digest is None):
                failures.append(f"{name}/{model.get('id')}: verified artifact is required for release")
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate Specialist Runtime release metadata")
    parser.add_argument("--require-artifacts", action="store_true", help="require every registered model to have a pinned URL and SHA256")
    parser.add_argument("--tag", help="verify a release tag matches project.version")
    args = parser.parse_args(argv)
    try:
        failures = check_registry(args.require_artifacts)
        if args.tag:
            expected_tag = f"v{project_version()}"
            if args.tag != expected_tag:
                failures.append(f"release tag {args.tag!r} does not match project version {expected_tag!r}")
    except (OSError, ValueError, TypeError) as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 2
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("release metadata checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
