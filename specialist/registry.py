"""Validated, data-first capability and model registry.

The checked-in ``registry/models.yaml`` uses JSON syntax (which is valid YAML)
so the core package can validate it without adding PyYAML to every install.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import Any


class RegistryError(RuntimeError):
    """Raised when the installed registry is missing or malformed."""


@dataclass(frozen=True)
class ArtifactFileSpec:
    path: str
    url: str
    sha256: str


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
    artifact_kind: str = "file"
    artifact_filename: str | None = None
    artifact_entrypoint: str | None = None
    artifact_files: tuple[ArtifactFileSpec, ...] = ()
    quality: float | None = None


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
    commercial_allowed_by_default: bool = False
    source_url: str | None = None
    models: tuple[ModelSpec, ...] = ()
    semantic_guarantees: tuple[str, ...] = ()
    quality_metrics: tuple[str, ...] = ()
    supports: dict[str, bool] = field(default_factory=dict)
    resource_profile: dict[str, Any] = field(default_factory=dict)
    privacy_level: str = "safe"
    determinism: str = "provider_defined"
    providers: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)

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
            kind = artifact.get("kind", "file")
            if kind not in {"file", "bundle", "server"}:
                raise RegistryError(f"{name}: artifact.kind must be 'file', 'bundle' or 'server'")
            filename = artifact.get("filename")
            if filename is not None and (not isinstance(filename, str) or not filename or Path(filename).name != filename):
                raise RegistryError(f"{name}: artifact.filename must be a simple file name")
            entrypoint = artifact.get("entrypoint")
            if entrypoint is not None and (not isinstance(entrypoint, str) or not entrypoint or Path(entrypoint).is_absolute() or ".." in Path(entrypoint).parts):
                raise RegistryError(f"{name}: artifact.entrypoint must be a relative path")
            artifact_files: list[ArtifactFileSpec] = []
            for file_item in artifact.get("files", []) or []:
                if not isinstance(file_item, dict):
                    raise RegistryError(f"{name}: artifact.files entries must be objects")
                file_path = file_item.get("path")
                file_url = file_item.get("url")
                file_sha = _validate_sha(file_item.get("sha256"), f"{name}.artifact.files.sha256")
                if not isinstance(file_path, str) or not file_path or Path(file_path).is_absolute() or ".." in Path(file_path).parts:
                    raise RegistryError(f"{name}: artifact file path must be relative")
                if not isinstance(file_url, str) or not file_url.startswith(("https://", "http://", "file://")) or not file_sha:
                    raise RegistryError(f"{name}: artifact files require a URL and SHA256")
                artifact_files.append(ArtifactFileSpec(file_path, file_url, file_sha))
            if kind == "bundle" and not artifact_files:
                raise RegistryError(f"{name}: bundle artifacts require at least one file")
            if kind == "bundle" and (url is not None or checksum is not None):
                raise RegistryError(f"{name}: bundle artifacts must use per-file digests and leave top-level URL/SHA256 null")
            if kind == "server" and (url is not None or checksum is not None or artifact.get("files")):
                raise RegistryError(f"{name}: server-managed artifacts cannot declare downloadable files")
            model_id = model.get("id")
            platforms = model.get("platforms")
            devices = model.get("devices")
            if not isinstance(model_id, str) or not model_id or not isinstance(platforms, list) or not platforms or not isinstance(devices, list) or not devices:
                raise RegistryError(f"{name}: model id, platforms and devices are required")
            quality = model.get("quality")
            if quality is not None and (isinstance(quality, bool) or not isinstance(quality, (int, float)) or not 0 <= float(quality) <= 1):
                raise RegistryError(f"{name}: model quality must be between 0 and 1")
            models.append(ModelSpec(model_id, bool(model.get("recommended", False)), int(model.get("memory_mb", 0)), int(model.get("disk_mb", 0)), tuple(platforms), tuple(devices), url, checksum, kind, filename, entrypoint, tuple(artifact_files), float(quality) if quality is not None else None))
        if not models or sum(model.recommended for model in models) != 1:
            raise RegistryError(f"{name}: exactly one recommended model is required")
        default_model = item["model"]
        if default_model not in {model.id for model in models}:
            raise RegistryError(f"{name}: default model is not listed in models")
        semantic = item.get("semantic_guarantees") or [item["description"]]
        if isinstance(semantic, str):
            semantic = [semantic]
        quality_metrics = item.get("quality_metrics") or ["quality", "latency_ms", "memory_mb"]
        if isinstance(quality_metrics, str):
            quality_metrics = [quality_metrics]
        default_supports = {"streaming": False, "batch": False, "local": True, "remote": False}
        supports = item.get("supports") or {}
        if isinstance(supports, dict):
            default_supports.update({str(key): bool(value) for key, value in supports.items()})
        resource_profile = item.get("resource_profile") or {}
        if not isinstance(resource_profile, dict):
            raise RegistryError(f"{name}: resource_profile must be an object")
        providers = item.get("providers") or [item["provider"]]
        if isinstance(providers, str):
            providers = [providers]
        result[name] = CapabilitySpec(
            name=name,
            command=item["command"],
            provider=item["provider"],
            model=default_model,
            modality=item["modality"],
            description=item["description"],
            bundle=item["bundle"],
            optional_dependency=item.get("optional_dependency"),
            license=license_info["weights"],
            commercial=bool(license_info.get("commercial", False)),
            commercial_allowed_by_default=bool(license_info.get("commercial_allowed_by_default", license_info.get("commercial", False))),
            source_url=source_url,
            models=tuple(models),
            semantic_guarantees=tuple(str(value) for value in semantic if str(value).strip()),
            quality_metrics=tuple(str(value) for value in quality_metrics if str(value).strip()),
            supports=default_supports,
            resource_profile=resource_profile,
            privacy_level=str(item.get("privacy_level") or "safe"),
            determinism=str(item.get("determinism") or "provider_defined"),
            providers=tuple(str(value) for value in providers if str(value).strip()),
            input_schema=dict(item.get("input_schema") or {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}, "options": {"type": "object"}}}),
            output_schema=dict(item.get("output_schema") or {"type": "object"}),
        )
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
            "input_schema": dict(spec.input_schema),
            "output_schema": dict(spec.output_schema),
            "bundle": spec.bundle,
            "optional_dependency": spec.optional_dependency,
            "source_url": spec.source_url,
            "license": {"code": REGISTRY_DOCUMENT.get("code_license", "MIT"), "weights": spec.license, "commercial": spec.commercial, "commercial_allowed_by_default": spec.commercial_allowed_by_default},
            "semantic_guarantees": list(spec.semantic_guarantees),
            "quality_metrics": list(spec.quality_metrics),
            "supports": dict(spec.supports),
            "resource_profile": dict(spec.resource_profile),
            "privacy_level": spec.privacy_level,
            "determinism": spec.determinism,
            "providers": list(spec.providers),
            "models": [
                {"id": model.id, "recommended": model.recommended, "quality": model.quality, "memory_mb": model.memory_mb, "disk_mb": model.disk_mb, "platforms": list(model.platforms), "devices": list(model.devices), "artifact": {"url": model.artifact_url, "sha256": model.artifact_sha256, "kind": model.artifact_kind, "filename": model.artifact_filename, "entrypoint": model.artifact_entrypoint, "files": [{"path": item.path, "url": item.url, "sha256": item.sha256} for item in model.artifact_files]}}
                for model in spec.models
            ],
        }
        for spec in CAPABILITIES.values()
    ]
