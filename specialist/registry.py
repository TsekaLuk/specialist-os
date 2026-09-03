"""Validated, data-first capability and model registry.

The checked-in ``registry/models.yaml`` uses JSON syntax (which is valid YAML)
so the core package can validate it without adding PyYAML to every install.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


class RegistryError(RuntimeError):
    """Raised when the installed registry is missing or malformed."""


@dataclass(frozen=True)
class ModelSpec:
    id: str
    recommended: bool
    memory_mb: int
    disk_mb: int
    platforms: tuple[str, ...]
    devices: tuple[str, ...]
    artifact_url: str | None = None
    artifact_sha256: str | None = None


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    command: str
    provider: str
    model: str
    modality: str
    description: str
    bundle: str
    optional_dependency: str | None = None
    license: str = "See provider terms"
    commercial: bool = False
    source_url: str | None = None
    models: tuple[ModelSpec, ...] = ()

    def model_spec(self, model_id: str | None = None) -> ModelSpec:
        wanted = model_id or self.model
        for item in self.models:
            if item.id == wanted:
                return item
        raise RegistryError(f"Model '{wanted}' is not registered for {self.name}")


def _registry_candidates() -> list[Path]:
    package_root = Path(__file__).resolve().parents[1]
    return [
        package_root / "registry" / "models.yaml",
        Path(sys.prefix) / "share" / "specialist" / "registry" / "models.yaml",
        Path(__file__).resolve().parent / "data" / "models.yaml",
    ]


def _validate_sha(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise RegistryError(f"{field} must be a 64-character hexadecimal SHA256 or null")
    return value.lower()


def _load_registry() -> tuple[dict[str, CapabilitySpec], dict[str, Any]]:
    path = next((candidate for candidate in _registry_candidates() if candidate.is_file()), None)
    if path is None:
        raise RegistryError("registry/models.yaml is not installed")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegistryError(f"could not parse registry {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or not isinstance(payload.get("capabilities"), list):
        raise RegistryError("registry must contain schema_version=1 and a capabilities array")
    result: dict[str, CapabilitySpec] = {}
    for item in payload["capabilities"]:
        if not isinstance(item, dict):
            raise RegistryError("each registry capability must be an object")
        required = {"name", "command", "provider", "model", "modality", "description", "bundle", "models", "source_url"}
        if not required.issubset(item):
            raise RegistryError(f"registry capability missing keys: {sorted(required.difference(item))}")
        name = item["name"]
        if not isinstance(name, str) or not name or name in result:
            raise RegistryError(f"invalid or duplicate capability name: {name!r}")
        license_info = item.get("license") or {}
        if not isinstance(license_info, dict) or not isinstance(license_info.get("weights"), str):
            raise RegistryError(f"{name}: license.weights is required")
        source_url = item.get("source_url")
        if source_url is not None and (not isinstance(source_url, str) or not source_url.startswith("https://")):
            raise RegistryError(f"{name}: source_url must be an HTTPS URL or null")
        models: list[ModelSpec] = []
        for model in item["models"]:
            if not isinstance(model, dict):
                raise RegistryError(f"{name}: model entries must be objects")
            artifact = model.get("artifact") or {}
            if not isinstance(artifact, dict):
                raise RegistryError(f"{name}: artifact must be an object")
            url = artifact.get("url")
            if url is not None and (not isinstance(url, str) or not url.startswith(("https://", "http://", "file://"))):
                raise RegistryError(f"{name}: artifact.url must be http(s), file, or null")
            checksum = _validate_sha(artifact.get("sha256"), f"{name}.artifact.sha256")
            if (url is None) != (checksum is None):
                raise RegistryError(f"{name}: artifact.url and artifact.sha256 must be specified together")
            model_id = model.get("id")
            platforms = model.get("platforms")
            devices = model.get("devices")
            if not isinstance(model_id, str) or not model_id or not isinstance(platforms, list) or not platforms or not isinstance(devices, list) or not devices:
                raise RegistryError(f"{name}: model id, platforms and devices are required")
            models.append(ModelSpec(model_id, bool(model.get("recommended", False)), int(model.get("memory_mb", 0)), int(model.get("disk_mb", 0)), tuple(platforms), tuple(devices), url, checksum))
        if not models or sum(model.recommended for model in models) != 1:
            raise RegistryError(f"{name}: exactly one recommended model is required")
        default_model = item["model"]
        if default_model not in {model.id for model in models}:
            raise RegistryError(f"{name}: default model is not listed in models")
        result[name] = CapabilitySpec(name, item["command"], item["provider"], default_model, item["modality"], item["description"], item["bundle"], item.get("optional_dependency"), license_info["weights"], bool(license_info.get("commercial", False)), source_url, tuple(models))
    return result, payload


CAPABILITIES, REGISTRY_DOCUMENT = _load_registry()
BUNDLES = {
    "vision": [name for name, spec in CAPABILITIES.items() if spec.bundle == "vision"],
    "audio": [name for name, spec in CAPABILITIES.items() if spec.bundle == "audio"],
    "document": [name for name, spec in CAPABILITIES.items() if spec.bundle == "document"],
    "all": list(CAPABILITIES),
}

ALIASES = {spec.command: name for name, spec in CAPABILITIES.items()}
ALIASES.update({name.replace(".", "_"): name for name in CAPABILITIES})


def resolve_capability(value: str) -> str:
    key = value.strip().lower()
    if key in CAPABILITIES:
        return key
    if key in ALIASES:
        return ALIASES[key]
    raise KeyError(f"Unknown capability '{value}'. Use 'specialist capabilities' to list available capabilities.")


def get_spec(value: str) -> CapabilitySpec:
    return CAPABILITIES[resolve_capability(value)]


def registry_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "capability": spec.name,
            "command": spec.command,
            "provider": spec.provider,
            "model": spec.model,
            "modality": spec.modality,
            "description": spec.description,
            "bundle": spec.bundle,
            "optional_dependency": spec.optional_dependency,
            "source_url": spec.source_url,
            "license": {"code": REGISTRY_DOCUMENT.get("code_license", "MIT"), "weights": spec.license, "commercial": spec.commercial},
            "models": [
                {"id": model.id, "recommended": model.recommended, "memory_mb": model.memory_mb, "disk_mb": model.disk_mb, "platforms": list(model.platforms), "devices": list(model.devices), "artifact": {"url": model.artifact_url, "sha256": model.artifact_sha256}}
                for model in spec.models
            ],
        }
        for spec in CAPABILITIES.values()
    ]
