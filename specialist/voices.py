"""Local, provider-neutral voice reference registry.

Voice records contain only a content-addressed artifact reference and optional
provider assets. Temporary references never enter this registry unless the
caller explicitly imports them.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any

from .artifacts import ArtifactStore, ArtifactError


_VOICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class VoiceRegistryError(ValueError):
    """Raised for invalid or missing voice records."""


class VoiceRegistry:
    def __init__(self, root: str | Path, artifacts: ArtifactStore | None = None):
        self.root = Path(root).expanduser()
        self.artifacts = artifacts or ArtifactStore(self.root.parent / "artifacts")

    @staticmethod
    def _validate_id(value: str) -> str:
        value = str(value).strip()
        if not _VOICE_ID.fullmatch(value):
            raise VoiceRegistryError("voice name must be 1-64 ASCII letters, numbers, dots, underscores or hyphens")
        return value

    def _path(self, voice_id: str) -> Path:
        return self.root / f"{self._validate_id(voice_id)}.json"

    def import_voice(self, source: str | Path, name: str, *, provider_assets: dict[str, Any] | None = None) -> dict[str, Any]:
        source_path = Path(source).expanduser()
        if source_path.is_symlink() or not source_path.is_file():
            raise VoiceRegistryError(f"voice reference must be a regular file: {source_path}")
        voice_id = self._validate_id(name)
        try:
            artifact = self.artifacts.put_file(source_path, mime="audio/wav", metadata={"kind": "voice_reference", "voice_id": voice_id})
        except ArtifactError as exc:
            raise VoiceRegistryError(str(exc)) from exc
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        record = {
            "id": voice_id,
            "uri": f"voice://{voice_id}",
            "source": {"artifact": artifact.uri, "filename": source_path.name},
            "provider_assets": dict(provider_assets or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        target = self._path(voice_id)
        if target.is_symlink():
            raise VoiceRegistryError("voice registry cannot write through a symlink")
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return record

    def get(self, value: str) -> dict[str, Any] | None:
        raw = str(value).strip()
        voice_id = raw.removeprefix("voice://")
        try:
            path = self._path(voice_id)
        except VoiceRegistryError:
            return None
        if not path.is_file() or path.is_symlink():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise VoiceRegistryError(f"voice record is corrupt: {voice_id}") from exc
        if not isinstance(record, dict) or record.get("id") != voice_id or record.get("uri") != f"voice://{voice_id}":
            raise VoiceRegistryError(f"voice record is invalid: {voice_id}")
        return record

    def require(self, value: str) -> dict[str, Any]:
        record = self.get(value)
        if record is None:
            raise VoiceRegistryError(f"voice '{value}' was not found; import it with `specialist voice import`")
        return record

    def artifact_path(self, record: dict[str, Any]) -> Path:
        source = record.get("source") if isinstance(record, dict) else None
        reference = source.get("artifact") if isinstance(source, dict) else None
        if not isinstance(reference, str):
            raise VoiceRegistryError("voice record has no source artifact")
        try:
            return self.artifacts.resolve(reference)
        except ArtifactError as exc:
            raise VoiceRegistryError(f"voice source artifact is unavailable: {exc}") from exc

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir() or self.root.is_symlink():
            return []
        values = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink():
                continue
            try:
                record = self.get(path.stem)
            except VoiceRegistryError:
                continue
            if record:
                values.append(record)
        return values

    def remove(self, value: str) -> bool:
        path = self._path(str(value).removeprefix("voice://"))
        if path.is_symlink():
            raise VoiceRegistryError("voice registry cannot remove through a symlink")
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

