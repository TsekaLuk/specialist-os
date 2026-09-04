"""Operator-facing Fish Audio installation metadata.

The runtime intentionally does not guess a CUDA/Docker deployment or download
an unpinned 4B model. This module exposes the supported configuration contract
for installers and control planes while lifecycle.py manages a configured
server command.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit


@dataclass(frozen=True)
class FishAudioInstallationPlan:
    endpoint: str
    execution: str
    start_policy: str
    recommended_gpu_memory_gb: int = 24
    license_mode: str = "research_only"

    def to_dict(self):
        return {
            "endpoint": self.endpoint,
            "execution": self.execution,
            "start_policy": self.start_policy,
            "recommended_gpu_memory_gb": self.recommended_gpu_memory_gb,
            "license_mode": self.license_mode,
            "managed_by": "operator",
        }


def installation_plan() -> FishAudioInstallationPlan:
    endpoint = os.environ.get("SPECIALIST_FISH_AUDIO_URL", "http://127.0.0.1:8080")
    execution = "local-server" if (urlsplit(endpoint).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"} else "remote-self-hosted-node"
    return FishAudioInstallationPlan(endpoint, execution, os.environ.get("SPECIALIST_FISH_AUDIO_START_POLICY", "on-demand"))
