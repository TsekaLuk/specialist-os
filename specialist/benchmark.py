"""Measured benchmark records used by the deterministic router."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import time
import threading
from typing import Any


@dataclass(frozen=True)
class BenchmarkRecord:
    capability: str
    provider: str
    model: str
    hardware: dict[str, Any]
    latency_ms: float
    warm_latency_ms: float | None = None
    peak_memory_mb: float | None = None
    quality: float | None = None
    runs: int = 1
    recorded_at: float = 0.0

    def to_dict(self):
        value = asdict(self)
        value["recorded_at"] = self.recorded_at or time.time()
        return value


class BenchmarkRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()

    def list(self, capability: str | None = None) -> list[dict[str, Any]]:
        if not self.path.is_file() or self.path.is_symlink():
            return []
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(values, list):
            return []
        return [item for item in values if isinstance(item, dict) and (capability is None or item.get("capability") == capability)]

    def record(self, record: BenchmarkRecord) -> dict[str, Any]:
        if record.latency_ms < 0 or not math.isfinite(float(record.latency_ms)) or record.warm_latency_ms is not None and (record.warm_latency_ms < 0 or not math.isfinite(float(record.warm_latency_ms))):
            raise ValueError("benchmark latency must be finite and non-negative")
        if self.path.is_symlink():
            raise OSError("benchmark registry cannot write through a symlink")
        with self._lock:
            values = self.list()
            item = record.to_dict()
            values.append(item)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.tmp")
            temporary.write_text(json.dumps(values, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            temporary.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
            return item

    def best(self, capability: str, *, hardware: dict[str, Any] | None = None) -> dict[str, Any] | None:
        values = self.list(capability)
        if hardware:
            fingerprint = {key: hardware.get(key) for key in ("os", "architecture", "cpu")}
            matching = [item for item in values if {key: (item.get("hardware") or {}).get(key) for key in fingerprint} == fingerprint]
            values = matching or values
        return min(values, key=lambda item: (float(item.get("latency_ms", float("inf"))), item.get("provider", ""), item.get("model", ""))) if values else None
