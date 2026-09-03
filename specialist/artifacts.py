"""Content-addressed artifact storage for large specialist outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from typing import Any, BinaryIO


_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ArtifactError(ValueError):
    """Raised when an artifact reference or storage operation is invalid."""


@dataclass(frozen=True)
class ArtifactRef:
    """Stable reference returned to callers instead of embedding large data."""

    id: str
    mime: str
    size_bytes: int
    sha256: str
    uri: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = {
            "id": self.id,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "uri": self.uri,
        }
        if self.metadata:
            value["metadata"] = dict(self.metadata)
        return value


class ArtifactStore:
    """Store immutable artifacts below ``~/.specialist/artifacts``.

    Files are addressed by SHA256 and written atomically. The store never
    follows a symlink when resolving a reference, which keeps artifact paths
    inside the configured root even when a provider is untrusted.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root).expanduser()

    @staticmethod
    def _digest(value: str) -> str:
        raw = str(value).strip()
        if raw.startswith("artifact://"):
            raw = raw.removeprefix("artifact://")
        if raw.startswith("artifact_"):
            raw = raw.removeprefix("artifact_")
        if not _DIGEST.fullmatch(raw):
            raise ArtifactError("artifact id must contain a SHA256 digest")
        return raw

    def _path(self, digest: str) -> Path:
        digest = self._digest(digest)
        return self.root / digest[:2] / digest[2:4] / digest

    def _metadata_path(self, digest: str) -> Path:
        return self._path(digest).with_name(self._path(digest).name + ".json")

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _mime(path: Path, explicit: str | None) -> str:
        if explicit and isinstance(explicit, str) and explicit.strip():
            return explicit.strip().lower()
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    @staticmethod
    def _write_metadata(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)

    def _write_stream(self, stream: BinaryIO, *, size_hint: int | None = None) -> tuple[str, int, Path]:
        self._ensure_root()
        digest = hashlib.sha256()
        size = 0
        temporary = None
        temporary_dir = self.root / ".tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile("wb", dir=temporary_dir, prefix="artifact-", delete=False) as target:
                temporary = Path(target.name)
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    if not isinstance(chunk, bytes):
                        raise ArtifactError("artifact source must provide bytes")
                    digest.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            final = self._path(digest.hexdigest())
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                if final.is_symlink() or not final.is_file():
                    raise ArtifactError("artifact destination is not a regular file")
                temporary.unlink(missing_ok=True)
            else:
                os.replace(temporary, final)
            return digest.hexdigest(), size, final
        finally:
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)

    def put_file(self, source: str | os.PathLike[str], *, mime: str | None = None, metadata: dict[str, Any] | None = None) -> ArtifactRef:
        path = Path(source).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactError(f"artifact source is not readable: {path}") from exc
        if not resolved.is_file():
            raise ArtifactError(f"artifact source is not a regular file: {path}")
        with resolved.open("rb") as stream:
            digest, size, final = self._write_stream(stream, size_hint=resolved.stat().st_size)
        value = {"source_name": resolved.name, **(metadata or {})}
        ref = ArtifactRef(f"artifact_{digest}", self._mime(resolved, mime), size, digest, f"artifact://{digest}", value)
        self._write_metadata(self._metadata_path(digest), ref.to_dict())
        return ref

    def put_bytes(self, data: bytes, *, mime: str = "application/octet-stream", metadata: dict[str, Any] | None = None) -> ArtifactRef:
        if not isinstance(data, bytes):
            raise ArtifactError("artifact data must be bytes")
        from io import BytesIO

        stream = BytesIO(data)
        digest, size, _final = self._write_stream(stream, size_hint=len(data))
        ref = ArtifactRef(f"artifact_{digest}", mime.strip().lower() or "application/octet-stream", size, digest, f"artifact://{digest}", dict(metadata or {}))
        self._write_metadata(self._metadata_path(digest), ref.to_dict())
        return ref

    def resolve(self, reference: str | ArtifactRef | dict[str, Any]) -> Path:
        if isinstance(reference, ArtifactRef):
            raw = reference.id
        elif isinstance(reference, dict):
            raw = reference.get("id") or reference.get("uri") or reference.get("sha256")
        else:
            raw = reference
        if not isinstance(raw, str):
            raise ArtifactError("artifact reference must contain id, uri or sha256")
        path = self._path(raw)
        # Check the unresolved path first. Resolving before this check would
        # hide a symlink and could make a reference escape the artifact root.
        try:
            if path.is_symlink() or any(parent.is_symlink() for parent in (path.parent, path.parent.parent, path.parent.parent.parent)):
                raise ArtifactError("artifact reference cannot traverse a symlink")
        except OSError as exc:
            raise ArtifactError("artifact does not exist") from exc
        try:
            resolved_root = self.root.resolve()
            resolved_path = path.resolve(strict=True)
        except OSError as exc:
            raise ArtifactError("artifact does not exist") from exc
        if not resolved_path.is_file() or not resolved_path.is_relative_to(resolved_root):
            raise ArtifactError("artifact reference is invalid")
        return resolved_path

    def metadata(self, reference: str | ArtifactRef | dict[str, Any]) -> dict[str, Any]:
        raw = reference.id if isinstance(reference, ArtifactRef) else (reference.get("id") or reference.get("uri") or reference.get("sha256")) if isinstance(reference, dict) else reference
        digest = self._digest(raw)
        path = self._metadata_path(digest)
        if not path.is_file() or path.is_symlink():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArtifactError("artifact metadata is corrupt") from exc
        return value if isinstance(value, dict) else {}

    def list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        values: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("[0-9a-f][0-9a-f]/[0-9a-f][0-9a-f]/*")):
            if path.is_file() and not path.is_symlink() and len(path.name) == 64 and _DIGEST.fullmatch(path.name):
                value = self.metadata(path.name)
                if value:
                    values.append(value)
                else:
                    values.append({"id": f"artifact_{path.name}", "sha256": path.name, "size_bytes": path.stat().st_size})
                if limit is not None and len(values) >= max(0, limit):
                    break
        return values
