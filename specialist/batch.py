"""Validated sequential execution through a shared runtime."""

import json
from pathlib import Path

from .registry import get_spec


def load_requests(path: Path):
    with path.open(encoding="utf-8") as stream:
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("request file exceeds 1 MiB")
    requests = json.loads(content)
    if not isinstance(requests, list) or not 1 <= len(requests) <= 256:
        raise ValueError("expected 1 to 256 requests")
    normalized = []
    for item in requests:
        if not isinstance(item, dict) or set(item) - {"capability", "input", "options"}:
            raise ValueError("requests accept capability, input and options only")
        if not isinstance(item.get("capability"), str):
            raise ValueError("capability must be a string")
        capability = get_spec(item["capability"]).name
        if not isinstance(item.get("input"), str) or not item["input"]:
            raise ValueError("input must be a nonempty local path or artifact URI")
        if not isinstance(item.get("options", {}), dict):
            raise ValueError("options must be an object")
        normalized.append({**item, "capability": capability})
    return normalized


def run_batch(runtime, requests, *, keep_going=False):
    results = []
    for item in requests:
        result = runtime.run(item["capability"], item["input"], item.get("options", {}))
        results.append(result)
        if result.get("error") and not keep_going:
            break
    return results
