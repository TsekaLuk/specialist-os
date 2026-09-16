"""Small SDK contract for third-party providers.

The SDK intentionally delegates lifecycle and isolation to SpecialistRuntime;
provider authors implement only model-specific behavior and a manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .provider_manifest import ProviderManifest
from .requirements import ProviderRequirement, evaluate_requirements


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
    # Adapters whose ``doctor`` contacts a network endpoint declare it here so
    # the runtime can keep endpoint contact off the default self-check path.
    doctor_probes_endpoint = False

    def doctor_endpoint(self):
        """Health URL to probe, or ``None`` when the adapter contacts nothing.

        Return ``{"url": ..., "headers": {...}, "expect": {...}}``. ``expect``
        carries the adapter's own health predicate - ``status`` (one code or a
        list), ``json_field`` and the ``accept`` values that field may hold - so
        a bounded caller reaches the same verdict as ``doctor`` instead of
        treating any answer as healthy. Without it only reachability is checked.
        """
        return None

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


def requirement(kind: str, name: str, purpose: str = "", *, optional: bool = False, group: str | None = None) -> ProviderRequirement:
    """Declare one provider prerequisite as manifest data.

    Requirements sharing a ``group`` are interchangeable sources of the same
    prerequisite and the group is satisfied when any member is.
    """
    return ProviderRequirement(kind, name, purpose, optional, group)


__all__ = ["ProviderAdapter", "ProviderRequirement", "ProviderResult", "evaluate_requirements", "provider_manifest", "requirement"]
