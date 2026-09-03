"""Authenticated remote Compute Fabric provider over the runtime HTTP API."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import urllib.error
import urllib.request

from .providers.ipc import WorkerError


class RemoteNodeProvider:
    requires_verified_artifact = False
    requires_provider_environment = False
    supported_platforms = ("macos-arm64", "linux-x64", "windows-x64")
    supported_devices = ("cpu", "mps", "cuda")
    memory_requirement_mb = 0
    disk_requirement_mb = 0
    license = "remote node terms"
    remote = True

    def __init__(self, node_id: str, capability: str, endpoint: str, *, token: str | None = None, latency_ms: int = 0, memory_mb: int = 0):
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("remote node endpoint must use HTTP(S)")
        self.node_id = node_id
        self.capability = capability
        self.name = f"node:{node_id}"
        self.model = "remote"
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.latency_ms = max(0, int(latency_ms))
        self.memory_requirement_mb = max(0, int(memory_mb))

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def install(self, cache, spec):
        cache.mark_installed(spec.name, self.name, self.model, source=self.endpoint, license_name=spec.license, commercial=spec.commercial, source_url=self.endpoint)
        return {"status": "ready", "remote": True, "node_id": self.node_id, "endpoint": self.endpoint}

    def doctor(self, hardware):
        request = urllib.request.Request(f"{self.endpoint}/health", headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return {"status": "ready" if payload.get("status") == "ok" else "not ready", "remote": True, "node_id": self.node_id, "health": payload}
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return {"status": "not ready", "remote": True, "node_id": self.node_id, "error": {"code": "remote_unreachable", "message": str(exc)}}

    def load(self):
        return self

    def unload(self):
        return None

    def infer(self, input_path: Path, options, cache):
        try:
            raw = input_path.read_bytes()
        except OSError as exc:
            raise WorkerError(f"could not read remote input: {exc}", code="input_read_failed", retryable=False) from exc
        if len(raw) > 512 * 1024 * 1024:
            raise WorkerError("remote input exceeds 512 MiB safety limit", code="input_too_large", retryable=False)
        payload = {"data_base64": base64.b64encode(raw).decode("ascii"), "filename": input_path.name, "options": options}
        request = urllib.request.Request(f"{self.endpoint}/v1/{self.capability.replace('.', '/')}", data=json.dumps(payload, ensure_ascii=True).encode("utf-8"), headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=float(options.get("timeout_seconds", 120))) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise WorkerError(f"remote node request failed: {exc}", code="remote_execution_failed", retryable=True) from exc
        if not isinstance(envelope, dict):
            raise WorkerError("remote node returned a non-object", code="remote_invalid_output", retryable=False)
        if envelope.get("error"):
            error = envelope["error"]
            raise WorkerError(error.get("message", "remote node failed"), code=error.get("code", "remote_execution_failed"), retryable=bool(error.get("retryable", False)))
        return envelope.get("result", {}), envelope.get("warnings", [])
