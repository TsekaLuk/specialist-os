"""Provider manifest parsing and discovery.

Manifests are intentionally data-only so third-party providers can be
inspected before any provider code is imported or executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Iterable


class ProviderManifestError(ValueError):
    """Raised when a provider manifest is missing or malformed."""


@dataclass(frozen=True)
class ProviderManifest:
    provider: str
    version: str
    capabilities: tuple[str, ...]
    runtime: dict[str, Any] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    license: dict[str, Any] = field(default_factory=dict)
    platform: dict[str, Any] = field(default_factory=dict)
    network_required: bool = False
    trust_level: str = "community"
    source: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, source: str | None = None) -> "ProviderManifest":
        if not isinstance(value, dict):
            raise ProviderManifestError("provider manifest must be an object")
        required = {"provider", "version", "runtime", "models", "metrics", "license", "platform"}
        missing = required.difference(value)
        if missing:
            raise ProviderManifestError(f"provider manifest missing keys: {sorted(missing)}")
        provider = value.get("provider")
        version = value.get("version")
        capabilities = value.get("capability", value.get("capabilities"))
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        if not isinstance(provider, str) or not provider.strip() or not isinstance(version, str) or not version.strip() or not isinstance(capabilities, list) or not capabilities or any(not isinstance(item, str) or not item.strip() for item in capabilities):
            raise ProviderManifestError("provider, version and capability must be non-empty strings")
        mappings = {key: value.get(key) for key in ("runtime", "models", "metrics", "license", "platform")}
        if any(not isinstance(item, dict) for item in mappings.values()):
            raise ProviderManifestError("runtime, models, metrics, license and platform must be objects")
        trust_level = str(value.get("trust_level") or "community")
        if trust_level not in {"official", "verified", "community", "experimental"}:
            raise ProviderManifestError("trust_level must be official, verified, community or experimental")
        network_required = value.get("network_required", False)
        if not isinstance(network_required, bool):
            raise ProviderManifestError("network_required must be boolean")
        return cls(provider.strip(), version.strip(), tuple(item.strip() for item in capabilities), runtime=mappings["runtime"], models=mappings["models"], metrics=mappings["metrics"], license=mappings["license"], platform=mappings["platform"], network_required=network_required, trust_level=trust_level, source=source)

    @classmethod
    def load(cls, path: str | Path) -> "ProviderManifest":
        manifest_path = Path(path).expanduser()
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ProviderManifestError(f"provider manifest is not a regular file: {manifest_path}")
        try:
            text = manifest_path.read_text(encoding="utf-8")
            try:
                payload = json.loads(text)
            except ValueError:
                # JSON is valid YAML and remains the dependency-free format;
                # PyYAML is used only when a contributor supplies real YAML.
                import yaml  # type: ignore

                payload = yaml.safe_load(text)
        except (OSError, ValueError, ImportError) as exc:
            raise ProviderManifestError(f"could not parse provider manifest {manifest_path}: {exc}") from exc
        return cls.from_dict(payload, source=str(manifest_path.resolve()))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "provider": self.provider,
            "version": self.version,
            "capability": list(self.capabilities),
            "capabilities": list(self.capabilities),
            "runtime": dict(self.runtime),
            "models": dict(self.models),
            "metrics": dict(self.metrics),
            "license": dict(self.license),
            "platform": dict(self.platform),
            "network_required": self.network_required,
            "trust_level": self.trust_level,
        }
        if self.source:
            value["source"] = self.source
        return value


def discover_manifests(roots: Iterable[str | Path]) -> list[ProviderManifest]:
    manifests: list[ProviderManifest] = []
    seen: set[str] = set()
    for root in roots:
        path = Path(root).expanduser()
        candidates = [path] if path.name in {"manifest.json", "manifest.yaml", "manifest.yml"} else sorted([*path.glob("*/manifest.json"), *path.glob("*/manifest.yaml"), *path.glob("*/manifest.yml")]) if path.exists() else []
        for candidate in candidates:
            try:
                manifest = ProviderManifest.load(candidate)
            except ProviderManifestError:
                continue
            if manifest.provider not in seen:
                seen.add(manifest.provider)
                manifests.append(manifest)
    return manifests


class ProviderCatalog:
    """Persistent, metadata-only provider catalog.

    Installing a manifest never imports or executes third-party code. Runtime
    execution still requires an explicit provider adapter, which keeps the
    trust boundary auditable while allowing discovery and validation first.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()

    def _manifest_path(self, provider: str) -> Path:
        safe = provider.strip().replace("/", "__").replace("\\", "__")
        if not safe or safe in {".", ".."} or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in safe):
            raise ProviderManifestError("provider name contains invalid characters")
        return self.root / safe / "manifest.json"

    def install(self, manifest: ProviderManifest) -> ProviderManifest:
        target = self._manifest_path(manifest.provider)
        if self.root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
            raise ProviderManifestError("provider catalog cannot write through a symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(json.dumps(manifest.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return ProviderManifest.load(target)

    def install_path(self, path: str | Path) -> ProviderManifest:
        return self.install(ProviderManifest.load(path))

    def list(self) -> list[ProviderManifest]:
        if not self.root.is_dir() or self.root.is_symlink():
            return []
        return discover_manifests([self.root])

    def get(self, provider: str) -> ProviderManifest | None:
        path = self._manifest_path(provider)
        if not path.is_file() or path.is_symlink():
            return None
        return ProviderManifest.load(path)


def builtin_manifests() -> list[ProviderManifest]:
    """Return safe metadata for the reference providers without importing them."""
    definitions = [
        ("yolo", ["vision.detect"], "8.3.0", "python", ["cpu", "mps", "cuda"], "AGPL-3.0"),
        ("sam", ["vision.segment"], "8.3.0", "python", ["cpu", "mps", "cuda"], "Apache-2.0"),
        ("paddleocr", ["vision.ocr"], "3.7.0", "python", ["cpu", "mps", "cuda"], "Apache-2.0"),
        ("depth-anything", ["vision.depth"], "2", "python", ["cpu", "mps", "cuda"], "Apache-2.0"),
        ("omniparser", ["screen.parse"], "2", "command", ["cpu", "mps", "cuda"], "MIT"),
        ("mineru", ["document.parse"], "3.4.5", "command", ["cpu", "cuda"], "AGPL-3.0"),
        ("whisper.cpp", ["audio.transcribe"], "1.9.2", "native", ["cpu", "mps", "cuda"], "MIT"),
        ("silero-vad", ["audio.vad"], "6.2.1", "python", ["cpu", "mps", "cuda"], "MIT"),
        ("fish_audio", ["speech.synthesize", "speech.clone_voice"], "S2", "http", ["cpu", "mps", "cuda"], "Fish Audio Research License"),
    ]
    manifests = [
        ProviderManifest(
            provider=name,
            version=version,
            capabilities=tuple(capabilities),
            runtime={"type": runtime, "accelerator": devices},
            models={},
            metrics={"quality": None, "latency_ms": None, "memory_mb": None},
            license={"code": license_name, "weights": license_name},
            platform={"macos_arm64": True, "linux_x64": True, "windows_x64": True},
            network_required=False,
            trust_level="official",
            source="builtin",
        )
        for name, capabilities, version, runtime, devices, license_name in definitions
    ]
    fish = next(item for item in manifests if item.provider == "fish_audio")
    manifests[manifests.index(fish)] = ProviderManifest(
        provider=fish.provider,
        version=fish.version,
        capabilities=fish.capabilities,
        runtime={"type": "http", "process_isolation": "required", "persistent_server": True, "start_policy": "on-demand", "max_concurrency": 1, "model_class": "heavy"},
        models={"default_model": "s2-pro", "recommended_gpu_memory_gb": 24},
        metrics={"ttfa_ms": None, "generation_latency_ms": None, "rtf": None, "audio_duration_ms": None, "peak_vram_mb": None},
        license={"family": "Fish Audio Research License", "commercial_allowed_by_default": False, "commercial": False},
        platform={"linux_x64": "supported", "windows_wsl": "supported", "macos_arm64": "experimental"},
        network_required=False,
        trust_level="official",
        source="builtin",
    )
    return manifests
