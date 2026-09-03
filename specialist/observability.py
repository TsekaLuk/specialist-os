"""Local-only structured execution events."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class EventLogger:
    def __init__(self, home: Path, enabled: bool = True):
        self.path = home / "logs" / "events.jsonl"
        self.enabled = enabled
        self._lock = threading.Lock()

    def emit(self, event: str, **fields: Any):
        if not self.enabled:
            return
        record = {"timestamp": time.time(), "event": event, **fields}
        payload = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > 64 * 1024:
            record = {"timestamp": record["timestamp"], "event": event, "fields_truncated": True}
            payload = (json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 10 * 1024 * 1024:
                rotated = self.path.with_suffix(".jsonl.1")
                rotated.unlink(missing_ok=True)
                self.path.replace(rotated)
            with self.path.open("ab") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
