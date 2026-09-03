"""Compute Fabric node metadata and deterministic scheduling primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import uuid
from typing import Any, Iterable


class NodeError(ValueError):
    """Raised for invalid node metadata or scheduling constraints."""


@dataclass(frozen=True)
class ComputeNode:
    node_id: str
    name: str
    capabilities: tuple[str, ...] = ()
    devices: tuple[str, ...] = ("cpu",)
    memory_mb: int = 0
    latency_ms: int = 0
    local: bool = True
    cost: float = 0.0
    privacy: str = "local"
    status: str = "ready"
    trust: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, **kwargs) -> "ComputeNode":
        return cls(node_id="node_" + uuid.uuid4().hex, name=name, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "name": self.name, "capabilities": list(self.capabilities), "devices": list(self.devices), "memory_mb": self.memory_mb, "latency_ms": self.latency_ms, "local": self.local, "cost": self.cost, "privacy": self.privacy, "status": self.status, "trust": self.trust, "metadata": dict(self.metadata)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ComputeNode":
        if not isinstance(value, dict) or not isinstance(value.get("node_id"), str) or not isinstance(value.get("name"), str):
            raise NodeError("node requires node_id and name")
        capabilities = value.get("capabilities", [])
        devices = value.get("devices", ["cpu"])
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise NodeError("node capabilities must be a string array")
        if not isinstance(devices, list) or not all(isinstance(item, str) for item in devices):
            raise NodeError("node devices must be a string array")
        memory = value.get("memory_mb", 0)
        latency = value.get("latency_ms", 0)
        cost = value.get("cost", 0.0)
        if isinstance(memory, bool) or not isinstance(memory, (int, float)) or int(memory) < 0 or isinstance(latency, bool) or not isinstance(latency, (int, float)) or int(latency) < 0 or isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(float(cost)) or float(cost) < 0:
            raise NodeError("node memory, latency and cost must be non-negative finite numbers")
        status = str(value.get("status", "ready"))
        if status not in {"ready", "degraded", "offline", "draining"}:
            raise NodeError("node status is invalid")
        return cls(value["node_id"], value["name"], tuple(capabilities), tuple(devices), int(memory), int(latency), bool(value.get("local", True)), float(cost), str(value.get("privacy", "local")), status, str(value.get("trust", "local")), dict(value.get("metadata") or {}))


class NodeRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()

    def register(self, node: ComputeNode) -> ComputeNode:
        if not node.node_id or "/" in node.node_id or "\\" in node.node_id:
            raise NodeError("node_id contains invalid characters")
        target = self.root / f"{node.node_id}.json"
        if self.root.is_symlink() or target.is_symlink():
            raise NodeError("node registry cannot write through a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(json.dumps(node.to_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        return node

    def list(self) -> list[ComputeNode]:
        if not self.root.is_dir() or self.root.is_symlink():
            return []
        values = []
        for path in sorted(self.root.glob("node_*.json")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                values.append(ComputeNode.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, NodeError):
                continue
        return values


class NodeScheduler:
    """Select a ready node with deterministic locality/cost ordering."""

    def select(self, capability: str, nodes: Iterable[ComputeNode], *, local_only: bool = False, max_latency_ms: int | None = None, max_memory_mb: int | None = None, trusted_network: bool = False) -> dict[str, Any]:
        candidates = []
        rejected = []
        for node in nodes:
            reasons = []
            if node.status != "ready":
                reasons.append(f"node status is {node.status}")
            if capability not in node.capabilities:
                reasons.append("capability is not advertised")
            if local_only and not node.local:
                reasons.append("local_only policy")
            if not node.local and not trusted_network:
                reasons.append("remote node requires trusted_network")
            if max_latency_ms is not None and node.latency_ms > max_latency_ms:
                reasons.append("latency limit")
            if max_memory_mb is not None and node.memory_mb and node.memory_mb > max_memory_mb:
                reasons.append("memory limit")
            item = {"node": node.to_dict(), "reasons": reasons, "allowed": not reasons}
            (candidates if not reasons else rejected).append(item)
        candidates.sort(key=lambda item: (not item["node"]["local"], item["node"]["latency_ms"], item["node"]["cost"], item["node"]["node_id"]))
        return {"capability": capability, "selected": candidates[0]["node"] if candidates else None, "candidates": candidates, "rejected": rejected}
