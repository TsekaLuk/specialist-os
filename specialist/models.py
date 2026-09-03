"""Model artifact lifecycle with atomic downloads and checksum verification."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.request
import urllib.error
import json
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

    def verify_bundle(self, root: Path, manifest_path: Path | None = None) -> dict:
        """Verify every file in an installed model bundle from its manifest."""
        root = root.expanduser()
        manifest_path = manifest_path or root / "artifact-manifest.json"
        if not root.is_dir() or not manifest_path.is_file():
            raise ModelArtifactError(f"model bundle is missing its manifest: {root}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ModelArtifactError(f"could not read model bundle manifest: {manifest_path}") from exc
        files = manifest.get("files") if isinstance(manifest, dict) else None
        if not isinstance(files, list) or not files:
            raise ModelArtifactError(f"model bundle manifest has no files: {manifest_path}")
        verified = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not SHA256_RE.fullmatch(str(item.get("sha256", ""))) or not isinstance(item.get("url"), str) or not item["url"].startswith(("https://", "http://", "file://")):
                raise ModelArtifactError(f"invalid model bundle manifest entry: {item!r}")
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ModelArtifactError(f"unsafe model bundle path: {relative}")
            file_path = root / relative
            digest = self.verify(file_path, item["sha256"])
            if item.get("size_bytes") is not None and item["size_bytes"] != file_path.stat().st_size:
                raise ModelArtifactError(f"model bundle size mismatch for {relative}")
            verified.append({"path": item["path"], "sha256": digest, "size_bytes": file_path.stat().st_size})
        canonical = json.dumps({"schema_version": manifest.get("schema_version"), "entrypoint": manifest.get("entrypoint"), "files": files}, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_sha256 = hashlib.sha256(canonical).hexdigest()
        expected_manifest = manifest.get("manifest_sha256")
        if expected_manifest and (not isinstance(expected_manifest, str) or not SHA256_RE.fullmatch(expected_manifest) or expected_manifest.lower() != manifest_sha256):
            raise ModelArtifactError(f"model bundle manifest checksum mismatch: expected {expected_manifest}, got {manifest_sha256}")
        entrypoint = manifest.get("entrypoint")
        if entrypoint:
            relative_entrypoint = Path(entrypoint)
            if relative_entrypoint.is_absolute() or ".." in relative_entrypoint.parts or not (root / relative_entrypoint).is_file():
                raise ModelArtifactError(f"model bundle entrypoint is invalid: {entrypoint}")
        return {"manifest": str(manifest_path), "files": verified, "entrypoint": entrypoint, "manifest_sha256": manifest_sha256}

    def download_bundle(self, files, destination: Path, *, entrypoint: str | None = None) -> dict:
        """Download and atomically install a multi-file model bundle.

        ``files`` must contain relative paths, HTTPS/file URLs and SHA256 values.
        A manifest is written last, so an interrupted install is never visible as
        a ready bundle.
        """
        if not files:
            raise ModelArtifactError("model bundle requires at least one file")
        destination = destination.expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
        manifest_files = []
        total_size = 0
        try:
            for item in files:
                relative = Path(item.path if hasattr(item, "path") else item["path"])
                url = item.url if hasattr(item, "url") else item["url"]
                checksum = item.sha256 if hasattr(item, "sha256") else item["sha256"]
                if relative.is_absolute() or ".." in relative.parts:
                    raise ModelArtifactError(f"unsafe model bundle path: {relative}")
                target = staging / relative
                self.download(url, target, expected_sha256=checksum)
                total_size += target.stat().st_size
                if total_size > self.max_bytes:
                    raise ModelArtifactError(f"model bundle exceeds {self.max_bytes} bytes")
                manifest_files.append({"path": relative.as_posix(), "url": url, "sha256": checksum, "size_bytes": target.stat().st_size})
            if entrypoint:
                relative_entrypoint = Path(entrypoint)
                if relative_entrypoint.is_absolute() or ".." in relative_entrypoint.parts:
                    raise ModelArtifactError(f"unsafe model bundle entrypoint: {entrypoint}")
                if not (staging / relative_entrypoint).is_file():
                    raise ModelArtifactError(f"model bundle entrypoint does not exist: {entrypoint}")
            manifest = {"schema_version": 1, "entrypoint": entrypoint, "files": manifest_files}
            canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
            manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
            self.cache._atomic_write(staging / "artifact-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            if destination.exists():
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()
            os.replace(staging, destination)
            return {"path": str(destination), "root": str(destination), "manifest": str(destination / "artifact-manifest.json"), "entrypoint": entrypoint, "files": manifest_files, "sha256": manifest["manifest_sha256"], "manifest_sha256": manifest["manifest_sha256"], "kind": "bundle"}
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

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
