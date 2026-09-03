"""Specialist capability graph execution.

Graphs are intentionally small DAGs for composing registered capabilities; the
runtime remains responsible for provider lifecycle, policy and provenance.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


class GraphError(ValueError):
    """Raised for invalid or failed capability graphs."""


@dataclass(frozen=True)
class GraphNode:
    name: str
    capability: str | None = None
    depends_on: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)
    executor: Callable[[dict[str, Any]], Any] | None = None
    fallback: tuple[str, ...] = ()
    condition: Callable[[dict[str, Any]], bool] | None = None


class SpecialistGraph:
    def __init__(self, name: str = "specialist-graph"):
        self.name = name
        self._nodes: dict[str, GraphNode] = {}

    def add(self, name: str, capability: str | None = None, *, depends_on=(), options=None, executor=None, fallback=(), condition=None) -> "SpecialistGraph":
        if not isinstance(name, str) or not name.strip() or name in self._nodes:
            raise GraphError(f"invalid or duplicate graph node: {name!r}")
        dependencies = tuple(depends_on) if not isinstance(depends_on, str) else (depends_on,)
        if any(not isinstance(item, str) or not item for item in dependencies):
            raise GraphError(f"{name}: depends_on must contain node names")
        if capability is None and executor is None:
            raise GraphError(f"{name}: capability or executor is required")
        self._nodes[name] = GraphNode(name, capability, dependencies, dict(options or {}), executor, tuple(fallback), condition)
        return self

    @property
    def nodes(self) -> tuple[GraphNode, ...]:
        return tuple(self._nodes.values())

    def _levels(self) -> list[list[GraphNode]]:
        unknown = {dep for node in self._nodes.values() for dep in node.depends_on if dep not in self._nodes}
        if unknown:
            raise GraphError(f"unknown graph dependencies: {sorted(unknown)}")
        pending = dict(self._nodes)
        levels: list[list[GraphNode]] = []
        while pending:
            ready = [node for node in pending.values() if all(dep not in pending for dep in node.depends_on)]
            if not ready:
                raise GraphError("graph contains a cycle")
            ready.sort(key=lambda node: node.name)
            levels.append(ready)
            for node in ready:
                pending.pop(node.name)
        return levels

    def execute(self, runtime, input_path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {"input": str(input_path), "options": dict(options or {}), "nodes": {}}
        trace: list[dict[str, Any]] = []
        for level in self._levels():
            def execute_node(node: GraphNode):
                dependencies = {name: context["nodes"][name] for name in node.depends_on}
                if node.condition is not None and not bool(node.condition({"input": str(input_path), "dependencies": dependencies, "options": context["options"]})):
                    return {"status": "skipped", "node": node.name}
                node_options = {**context["options"], **node.options}
                if dependencies:
                    node_options["dependencies"] = dependencies
                try:
                    if node.executor is not None:
                        value = node.executor({"input": str(input_path), "dependencies": dependencies, "options": node_options})
                    else:
                        value = runtime.run(node.capability, input_path, node_options)
                        if value.get("error") and node.fallback:
                            for fallback in node.fallback:
                                value = runtime.run(fallback, input_path, node_options)
                                if not value.get("error"):
                                    break
                    return value
                except Exception as exc:
                    return {"error": {"code": "graph_node_failed", "message": str(exc), "retryable": False}, "node": node.name}

            with ThreadPoolExecutor(max_workers=max(1, len(level)), thread_name_prefix="specialist-graph") as pool:
                values = list(pool.map(execute_node, level))
            for node, value in zip(level, values):
                context["nodes"][node.name] = value
                node_status = "error" if isinstance(value, dict) and value.get("error") else (value.get("status", "completed") if isinstance(value, dict) else "completed")
                trace.append({"node": node.name, "capability": node.capability, "status": node_status})
        failed = [name for name, value in context["nodes"].items() if isinstance(value, dict) and value.get("error")]
        return {"graph": self.name, "status": "failed" if failed else "completed", "nodes": context["nodes"], "trace": trace, "failed_nodes": failed}
