"""Model, result and local metadata cache."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .rust_core import rust_cache_key


def specialist_home(home: str | os.PathLike[str] | None = None) -> Path:
    root = home or os.environ.get("SPECIALIST_HOME")
    return Path(root).expanduser() if root else Path.home() / ".specialist"


class Cache:
    MODEL_STATES = {"available", "downloading", "ready", "loading", "running", "unloaded", "corrupt", "error"}

    def __init__(self, home=None):
        self.home = specialist_home(home)
        self.models = self.home / "models"
        self.results = self.home / "cache" / "results"
        self.environments = self.home / "environments"
        self.logs = self.home / "logs"
        self.metadata = self.home / "metadata"
        self.locks = self.home / "locks"

    def ensure_dirs(self):
        for path in (self.models, self.results, self.environments, self.logs, self.metadata, self.locks):
            path.mkdir(parents=True, exist_ok=True)

    def input_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def result_key(self, path: Path, capability: str, provider: str, model: str, options: dict[str, Any]) -> str:
        input_digest = self.input_hash(path)
        options_json = json.dumps(options, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if rust_cache_key:
            return rust_cache_key(input_digest, capability, provider, model, options_json)
        payload = {"input": input_digest, "capability": capability, "provider": provider, "model": model, "options": options}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def result_path(self, key: str) -> Path:
        return self.results / f"{key}.json"

    def read_result(self, key: str):
        path = self.result_path(key)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            try:
                os.utime(path, None)
            except OSError:
                pass
            return value
        except (OSError, ValueError):
            return None

    def write_result(self, key: str, value: dict[str, Any]):
        self.ensure_dirs()
        target = self.result_path(key)
        self._atomic_write(target, json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n")
        return target

    def remove_result(self, key: str) -> bool:
        target = self.result_path(key)
        try:
            target.unlink()
            return True
        except FileNotFoundError:
            return False

    def _atomic_write(self, target: Path, content: str):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            try:
                directory_fd = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except (OSError, AttributeError):
                pass
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def installed_marker(self, capability: str) -> Path:
        return self.metadata / (capability.replace(".", "__") + ".json")

    def mark_installed(self, capability, provider, model, status="ready", license_name=None, source="builtin", sha256=None, download_date=None, artifact_path=None, commercial=None, source_url=None, **extra):
        if status not in self.MODEL_STATES:
            raise ValueError(f"unknown model state: {status}")
        self.ensure_dirs()
        marker = self.installed_marker(capability)
        current = self.installation(capability) or {}
        payload = {"capability": capability, "provider": provider, "model": model, "version": model, "sha256": sha256, "source": source, "artifact_path": str(artifact_path) if artifact_path else None, "license": license_name, "code_license": "MIT", "commercial": commercial, "source_url": source_url, "download_date": download_date or current.get("download_date") or datetime.now(timezone.utc).isoformat(), "status": status, "state_changed": datetime.now(timezone.utc).isoformat(), **extra}
        if "pinned" in current:
            payload["pinned"] = current["pinned"]
        self._atomic_write(marker, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        marker.with_suffix(".error.json").unlink(missing_ok=True)
        return payload

    def mark_error(self, capability, provider, model, message, **extra):
        """Persist a failed lifecycle state without making it look installed."""
        self.ensure_dirs()
        marker = self.installed_marker(capability)
        payload = {"capability": capability, "provider": provider, "model": model, "version": model, "status": "error", "message": str(message), "state_changed": datetime.now(timezone.utc).isoformat(), **extra}
        self._atomic_write(marker.with_suffix(".error.json"), json.dumps(payload, indent=2, sort_keys=True) + "\n")
        marker.unlink(missing_ok=True)
        return payload

    def update_state(self, capability, status: str, **fields):
        if status not in self.MODEL_STATES:
            raise ValueError(f"unknown model state: {status}")
        installation = self.installation(capability)
        if installation is None:
            return None
        installation.update(fields)
        installation["status"] = status
        installation["state_changed"] = datetime.now(timezone.utc).isoformat()
        self._atomic_write(self.installed_marker(capability), json.dumps(installation, indent=2, sort_keys=True) + "\n")
        return installation

    def installation(self, capability):
        marker = self.installed_marker(capability)
        if not marker.exists():
            return None
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def error_state(self, capability):
        marker = self.installed_marker(capability).with_suffix(".error.json")
        if not marker.exists():
            return None
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"capability": capability, "status": "error", "message": "corrupt error marker"}

    @contextmanager
    def capability_lock(self, capability):
        """Coordinate installation across runtime processes where possible."""
        self.ensure_dirs()
        path = self.locks / (capability.replace(".", "__") + ".lock")
        stream = path.open("a+", encoding="utf-8")
        try:
            try:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            yield
        finally:
            try:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            stream.close()

    def remove_model(self, capability):
        marker = self.installed_marker(capability)
        error_marker = marker.with_suffix(".error.json")
        removed = error_marker.exists()
        if marker.exists():
            installation = self.installation(capability)
            artifact = Path(installation["artifact_path"]).expanduser() if installation and installation.get("artifact_path") else None
            marker.unlink()
            removed = True
            if artifact and self.models in artifact.parents:
                if artifact.is_dir():
                    import shutil

                    shutil.rmtree(artifact)
                elif artifact.is_file():
                    artifact.unlink()
        error_marker.unlink(missing_ok=True)
        return removed

    def set_pinned(self, capability, pinned=True):
        marker = self.installed_marker(capability)
        installation = self.installation(capability) or {"capability": capability}
        installation["pinned"] = bool(pinned)
        self.ensure_dirs()
        self._atomic_write(marker, json.dumps(installation, indent=2) + "\n")
        return installation

    def clean_results(self, max_age_seconds=None, max_entries=None):
        count = 0
        candidates = []
        if not self.results.exists():
            return count
        for path in self.results.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                capability = value.get("capability")
                installation = self.installation(capability) if capability else None
                if installation and installation.get("pinned"):
                    continue
                candidates.append((path, path.stat().st_atime))
            except (OSError, ValueError):
                candidates.append((path, 0))
        now = time.time()
        for path, accessed in sorted(candidates, key=lambda item: item[1]):
            expired = max_age_seconds is not None and now - accessed > max_age_seconds
            over_limit = max_entries is not None and len(candidates) - count > max_entries
            if expired or over_limit:
                path.unlink(missing_ok=True)
                count += 1
        return count
