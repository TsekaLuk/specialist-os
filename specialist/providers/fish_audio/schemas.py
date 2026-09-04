"""Provider-local audio response metadata; generic semantics stay in Core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioMetadata:
    mime: str
    duration_ms: int | float | None
    sample_rate: int | float | None
    path: str
    temporary: bool = True

    def to_dict(self):
        return {"mime": self.mime, "duration_ms": self.duration_ms, "sample_rate": self.sample_rate, "path": self.path, "temporary": self.temporary}

