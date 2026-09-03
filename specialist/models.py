"""Model artifact lifecycle with atomic downloads and checksum verification."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.request
import urllib.error
from pathlib import Path


class ModelArtifactError(RuntimeError):
    pass


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ModelManager:
    def __init__(self, cache, timeout=60, max_bytes=20 * 1024**3):
        self.cache = cache
        self.timeout = timeout
        self.max_bytes = max_bytes

    def verify(self, path: Path, expected_sha256: str | None = None) -> str:
        if not path.is_file():
            raise ModelArtifactError(f"model artifact does not exist: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        if expected_sha256 and (not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256) or value.lower() != expected_sha256.lower()):
            raise ModelArtifactError(f"checksum mismatch for {path}: expected {expected_sha256}, got {value}")
        return value

    def ensure_capacity(self, destination: Path, expected_bytes: int | None = None):
        if not expected_bytes or expected_bytes <= 0:
            return
        try:
            free = shutil.disk_usage(destination.parent).free
        except OSError:
            return
        if free < expected_bytes:
            raise ModelArtifactError(f"insufficient disk space: need at least {expected_bytes} bytes in {destination.parent}, have {free}")

    def download(self, url: str, destination: Path, expected_sha256: str | None = None) -> dict:
        if not isinstance(url, str) or not url.startswith(("https://", "http://", "file://")):
            raise ModelArtifactError("model source must use https://, http://, or file://")
        if not isinstance(expected_sha256, str) or not SHA256_RE.fullmatch(expected_sha256):
            raise ModelArtifactError("a valid 64-character SHA256 is required for every model artifact")
        destination = destination.expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            available = shutil.disk_usage(destination.parent).free
            if available < 1:
                raise ModelArtifactError(f"insufficient disk space for model destination: {destination.parent}")
        except OSError:
            pass
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        size = 0
        digest = hashlib.sha256()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "specialist-runtime/0.1"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response, os.fdopen(fd, "wb") as stream:
                final_url = response.geturl()
                if url.startswith("https://") and final_url.startswith("http://"):
                    raise ModelArtifactError("refusing HTTPS model download redirected to plain HTTP")
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > self.max_bytes:
                            raise ModelArtifactError(f"model download exceeds {self.max_bytes} bytes")
                    except ValueError:
                        pass
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ModelArtifactError(f"model download exceeds {self.max_bytes} bytes")
                    digest.update(chunk)
                    stream.write(chunk)
            actual = digest.hexdigest()
            if actual.lower() != expected_sha256.lower():
                raise ModelArtifactError(f"checksum mismatch: expected {expected_sha256}, got {actual}")
            os.replace(temporary, destination)
            return {"path": str(destination), "size_bytes": size, "sha256": actual, "source": url}
        except ModelArtifactError:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            try:
                os.close(fd)
            except OSError:
                pass
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise ModelArtifactError(f"model download failed: {exc}") from exc
