"""Aurelius v2 workflow graph.

This ports the original DAG-style workflow execution idea into a compact,
standalone utility for sequential and parallel callable orchestration.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass(slots=True)
class WorkflowNode:
    node_id: str
    fn: Callable[..., Any]
    deps: list[str] = field(default_factory=list)
    status: NodeStatus = NodeStatus.PENDING


@dataclass(slots=True)
class WorkflowResult:
    node_id: str
    output: Any
    error: str | None
    duration_ms: float


class WorkflowGraph:
    """DAG workflow with sequential and parallel execution modes."""

    def __init__(self) -> None:
        self._nodes: dict[str, WorkflowNode] = {}

    def add_node(
        self,
        node_id: str,
        fn: Callable[..., Any],
        deps: list[str] | None = None,
    ) -> None:
        """Register a node. Raises ValueError on duplicate node_id."""
        if node_id in self._nodes:
            raise ValueError(f"Node '{node_id}' already registered.")
        self._nodes[node_id] = WorkflowNode(node_id=node_id, fn=fn, deps=list(deps or []))

    def validate(self) -> list[str]:
        """Return a list of graph validation errors."""
        white, gray, black = 0, 1, 2
        colour: dict[str, int] = {nid: white for nid in self._nodes}
        errors: list[str] = []

        for node in self._nodes.values():
            for dep in node.deps:
                if dep not in self._nodes:
                    errors.append(f"Node '{node.node_id}' depends on undefined node '{dep}'.")

        def dfs(nid: str) -> None:
            colour[nid] = gray
            for dep in self._nodes[nid].deps:
                if dep not in self._nodes:
                    continue
                if colour[dep] == gray:
                    errors.append(f"Cycle detected: '{dep}' is an ancestor of '{nid}'.")
                elif colour[dep] == white:
                    dfs(dep)
            colour[nid] = black

        for nid in list(self._nodes):
            if colour[nid] == white:
                dfs(nid)

        return errors

    def _topological_sort(self) -> list[str]:
        """Return node IDs in dependency order."""
        visited: set[str] = set()
        order: list[str] = []

        def visit(nid: str) -> None:
            if nid in visited:
                return
            visited.add(nid)
            for dep in self._nodes[nid].deps:
                if dep in self._nodes:
                    visit(dep)
            order.append(nid)

        for nid in self._nodes:
            visit(nid)
        return order

    def _run_node(self, node: WorkflowNode, state: dict[str, Any]) -> WorkflowResult:
        node.status = NodeStatus.RUNNING
        started = time.perf_counter()
        try:
            output = node.fn(state)
            node.status = NodeStatus.COMPLETED
            return WorkflowResult(
                node_id=node.node_id,
                output=output,
                error=None,
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            node.status = NodeStatus.FAILED
            return WorkflowResult(
                node_id=node.node_id,
                output=None,
                error=str(exc),
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )

    def run_sequential(self, state: dict[str, Any]) -> dict[str, WorkflowResult]:
        """Execute nodes in topological order, mutating shared state with dict outputs."""
        order = self._topological_sort()
        results: dict[str, WorkflowResult] = {}

        for nid in order:
            node = self._nodes[nid]
            result = self._run_node(node, state)
            results[nid] = result
            if result.error is None and result.output is not None:
                if isinstance(result.output, dict):
                    state.update(result.output)
                else:
                    state[nid] = result.output

        return results

    def run_parallel(
        self,
        state: dict[str, Any],
        max_workers: int = 4,
    ) -> dict[str, WorkflowResult]:
        """Execute nodes in parallel as soon as dependencies are satisfied."""
        for node in self._nodes.values():
            node.status = NodeStatus.PENDING

        results: dict[str, WorkflowResult] = {}
        in_flight: dict[str, Future] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while True:
                done_ids = [nid for nid, fut in in_flight.items() if fut.done()]
                for nid in done_ids:
                    result = in_flight.pop(nid).result()
                    results[nid] = result
                    if result.error is None and result.output is not None:
                        if isinstance(result.output, dict):
                            state.update(result.output)
                        else:
                            state[nid] = result.output

                submitted = False
                for nid, node in self._nodes.items():
                    if node.status != NodeStatus.PENDING or nid in in_flight:
                        continue
                    deps_ok = all(
                        self._nodes[dep].status == NodeStatus.COMPLETED
                        for dep in node.deps
                        if dep in self._nodes
                    )
                    if deps_ok:
                        in_flight[nid] = executor.submit(self._run_node, node, dict(state))
                        submitted = True

                all_done = all(
                    node.status in {NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED}
                    for node in self._nodes.values()
                )
                if all_done and not in_flight:
                    break

                if not submitted and not in_flight:
                    for nid, node in self._nodes.items():
                        if node.status == NodeStatus.PENDING:
                            node.status = NodeStatus.SKIPPED
                            results[nid] = WorkflowResult(
                                node_id=nid,
                                output=None,
                                error="Skipped: dependency failed or cycle.",
                                duration_ms=0.0,
                            )
                    break

                if in_flight:
                    next(as_completed(in_flight.values()), None)

        return results

    def node_merge(self, results: dict[str, WorkflowResult]) -> dict[str, Any]:
        """Merge successful node outputs into a single dictionary."""
        merged: dict[str, Any] = {}
        for result in results.values():
            if result.error is None and result.output is not None:
                if isinstance(result.output, dict):
                    merged.update(result.output)
                else:
                    merged[result.node_id] = result.output
        return merged


AGENT_REGISTRY: dict[str, Any] = {
    "workflow_graph": WorkflowGraph,
}


__all__ = [
    "AGENT_REGISTRY",
    "NodeStatus",
    "WorkflowGraph",
    "WorkflowNode",
    "WorkflowResult",
]
