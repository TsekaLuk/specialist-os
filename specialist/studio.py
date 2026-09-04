"""Machine-readable Specialist Studio control-plane snapshot."""

from __future__ import annotations

import json
from typing import Any


def snapshot(runtime, *, recent_limit: int = 20) -> dict[str, Any]:
    events = []
    path = runtime.cache.logs / "events.jsonl"
    if path.is_file() and not path.is_symlink():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-max(0, int(recent_limit)):]
            events = [json.loads(line) for line in lines if line.strip()]
        except (OSError, ValueError):
            events = []
    readiness = runtime.readiness()
    return {
        "status": readiness.get("status"),
        "health": {"backend": readiness.get("backend"), "isolate": readiness.get("isolate"), "ready_capabilities": readiness.get("ready_capabilities"), "capabilities": readiness.get("capabilities")},
        "capabilities": runtime.capabilities(),
        "models": runtime.models(),
        "nodes": [node.to_dict() for node in runtime.nodes.list()],
        "benchmarks": runtime.benchmarks.list(),
        "metrics": runtime.metrics(),
        "recent_runs": events,
    }
