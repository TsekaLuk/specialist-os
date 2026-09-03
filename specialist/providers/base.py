"""Provider protocol used by the capability runtime."""

from __future__ import annotations

from typing import Any, Protocol


class Provider(Protocol):
    name: str
    capability: str
    model: str
    supported_platforms: tuple[str, ...]
    supported_devices: tuple[str, ...]
    memory_requirement_mb: int
    disk_requirement_mb: int
    license: str

    def install(self, cache, spec): ...

    def doctor(self, hardware) -> dict[str, Any]: ...

    def load(self): ...

    def infer(self, input_path, options, cache) -> tuple[dict[str, Any], list[str]]: ...

    def unload(self): ...
