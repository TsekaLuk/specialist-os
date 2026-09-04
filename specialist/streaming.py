"""Stateful streaming/session protocol for specialist capabilities."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import threading
import time
import uuid
import weakref
from pathlib import Path
from typing import Any


class SessionError(ValueError):
    """Raised when a stream session is used after it is closed or malformed."""


@dataclass
class SpecialistSession:
    runtime: Any
    capability: str
    options: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: "session_" + uuid.uuid4().hex)
    _events: deque[dict[str, Any]] = field(default_factory=deque, init=False)
    _sequence: int = field(default=0, init=False)
    _closed: bool = field(default=False, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _provider_state: Any = field(default=None, init=False)

    def __post_init__(self):
        provider = self.runtime.providers.get(self.capability)
        if provider is not None and hasattr(provider, "open_session"):
            self._provider_state = provider.open_session(dict(self.options))

    def push(self, value: str | Path | bytes, **metadata) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise SessionError("session is closed")
            provider = self.runtime.providers.get(self.capability)
            if self._provider_state is not None and hasattr(provider, "push"):
                result = provider.push(self._provider_state, value, dict(metadata))
            else:
                if isinstance(value, bytes):
                    ref = self.runtime.artifacts.put_bytes(value, metadata={"session_id": self.id, **metadata})
                    input_path = self.runtime.artifacts.resolve(ref)
                elif isinstance(value, (str, Path)):
                    input_path = value
                else:
                    raise SessionError("session input must be a path or bytes")
                result = self.runtime.run(self.capability, input_path, self.options)
            self._sequence += 1
            event = {"event": "result", "session_id": self.id, "sequence": self._sequence, "timestamp": time.time(), "data": result}
            self._events.append(event)
            return event

    def poll(self, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            count = len(self._events) if limit is None else max(0, int(limit))
            return [self._events.popleft() for _ in range(min(count, len(self._events)))]

    def close(self) -> dict[str, Any]:
        with self._lock:
            if not self._closed:
                provider = self.runtime.providers.get(self.capability)
                if self._provider_state is not None and provider is not None and hasattr(provider, "close_session"):
                    provider.close_session(self._provider_state)
                self._closed = True
            return {"session_id": self.id, "event": "closed", "sequence": self._sequence}


class SessionManager:
    def __init__(self, runtime):
        # The manager lives on the runtime, so keeping a strong reference here
        # would create a cycle and defer runtime cleanup until interpreter
        # shutdown. A weak reference lets worker processes close promptly.
        self._runtime = weakref.ref(runtime)
        self._sessions: dict[str, SpecialistSession] = {}
        self._lock = threading.RLock()

    def open(self, capability: str, options: dict[str, Any] | None = None) -> SpecialistSession:
        runtime = self._runtime()
        if runtime is None:
            raise SessionError("runtime is no longer available")
        session = SpecialistSession(runtime, capability, dict(options or {}))
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> SpecialistSession:
        with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError as exc:
                raise SessionError(f"unknown session '{session_id}'") from exc

    def close_all(self):
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
