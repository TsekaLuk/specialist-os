"""Small SDK contract for third-party providers.

The SDK intentionally delegates lifecycle and isolation to SpecialistRuntime;
provider authors implement only model-specific behavior and a manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .provider_manifest import ProviderManifest


@dataclass(frozen=True)
class ProviderResult:
    result: dict[str, Any]
    warnings: tuple[str, ...] = ()


class ProviderAdapter:
    name = "provider"
    capability = ""
    model = ""
    supported_devices = ("cpu",)
    requires_verified_artifact = True

    def install(self, cache, spec):
        return {"status": "ready"}

    def doctor(self, hardware):
        return {"status": "ready"}

    def load(self):
        return self

    def infer(self, input_path, options, cache):
        raise NotImplementedError

    def unload(self):
        return None

    @classmethod
    def validate_manifest(cls, manifest: ProviderManifest) -> ProviderManifest:
        if cls.capability and cls.capability not in manifest.capabilities:
            raise ValueError(f"manifest does not advertise {cls.capability}")
        if manifest.provider != cls.name:
            raise ValueError(f"manifest provider '{manifest.provider}' does not match adapter '{cls.name}'")
        return manifest


def provider_manifest(**fields) -> ProviderManifest:
    """Build and validate manifest metadata in provider package setup code."""
    return ProviderManifest.from_dict(fields)
