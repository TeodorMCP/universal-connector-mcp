"""Dependency-graph (DAG) execution for ``execute_graph``.

Unlike ``execute_chained`` (an explicitly ordered list with manual parallel
groups), the graph planner derives the execution order automatically:

* Each node declares an ``id``. Any ``${other_id.path}`` reference inside a
  node's params creates an edge ``other_id -> this node``. Explicit
  ``depends_on: ["id", ...]`` adds ordering edges without data flow.
* Nodes with no outstanding dependencies run concurrently (bounded by
  ``max_concurrency``); a node starts as soon as all its dependencies succeed.
* If a node fails, its transitive dependents are skipped, but independent
  branches keep running.

The planner is transport- and executor-agnostic: it only orchestrates. The
caller supplies ``run_node`` to actually resolve refs and execute an operation.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

_REF_PATTERN = re.compile(r"\$\{([^}]+)\}")

RunNode = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


class GraphError(ValueError):
    """Raised when the graph is structurally invalid (bad refs, cycles, ...)."""


def _iter_ref_ids(value: Any) -> set[str]:
    """Collect the node ids referenced by ``${id.path}`` markers anywhere in *value*."""
    found: set[str] = set()
    if isinstance(value, str):
        for match in _REF_PATTERN.finditer(value):
            expr = match.group(1).strip()
            head = expr.split(".", 1)[0].strip()
            if head:
                found.add(head)
    elif isinstance(value, dict):
        for item in value.values():
            found |= _iter_ref_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= _iter_ref_ids(item)
    return found


def build_dependencies(nodes: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Validate the node list and return ``{node_id: {dependency_ids}}``.

    Raises GraphError on missing ids, duplicate ids, references to unknown
    nodes, self-references, or dependency cycles.
    """
    if not nodes:
        raise GraphError("execute_graph requires at least one node.")

    ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise GraphError("Each node must be an object.")
        node_id = node.get("id")
        if not node_id or not isinstance(node_id, str):
            raise GraphError("Each node needs a non-empty string 'id'.")
        if not node.get("operation_id"):
            raise GraphError(f"Node '{node_id}' is missing 'operation_id'.")
        ids.append(node_id)

    id_set = set(ids)
    if len(id_set) != len(ids):
        dupes = {i for i in ids if ids.count(i) > 1}
        raise GraphError(f"Duplicate node id(s): {', '.join(sorted(dupes))}.")

    deps: dict[str, set[str]] = {}
    for node in nodes:
        node_id = node["id"]
        referenced = _iter_ref_ids(node.get("params", {}))
        explicit = node.get("depends_on") or []
        if isinstance(explicit, str):
            explicit = [explicit]
        edges = set(referenced) | set(explicit)
        edges.discard(node_id)  # a self-reference is just "no dependency"
        unknown = edges - id_set
        if unknown:
            raise GraphError(
                f"Node '{node_id}' depends on unknown node(s): {', '.join(sorted(unknown))}."
            )
        deps[node_id] = edges

    _assert_acyclic(deps)
    return deps


def _assert_acyclic(deps: dict[str, set[str]]) -> None:
    """Kahn's algorithm: if not all nodes can be ordered, there is a cycle."""
    indegree = {node: len(edges) for node, edges in deps.items()}
    dependents: dict[str, list[str]] = {node: [] for node in deps}
    for node, edges in deps.items():
        for dep in edges:
            dependents[dep].append(node)

    queue = [n for n, d in indegree.items() if d == 0]
    seen = 0
    while queue:
        current = queue.pop()
        seen += 1
        for child in dependents[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if seen != len(deps):
        stuck = sorted(n for n, d in indegree.items() if d > 0)
        raise GraphError(f"Dependency cycle detected among node(s): {', '.join(stuck)}.")


async def run_graph(
    nodes: list[dict[str, Any]],
    run_node: RunNode,
    *,
    max_concurrency: int = 8,
) -> dict[str, dict[str, Any]]:
    """Execute *nodes* honoring dependencies, running independent nodes in parallel.

    Returns ``{node_id: result}``. A node whose dependency failed (or was itself
    skipped) is not run; its result is ``{"ok": False, "skipped": True,
    "skipped_because": <dependency_id>}``.
    """
    deps = build_dependencies(nodes)
    node_by_id = {node["id"]: node for node in nodes}

    remaining = {node_id: set(edges) for node_id, edges in deps.items()}
    context: dict[str, Any] = {}
    results: dict[str, dict[str, Any]] = {}
    failed: set[str] = set()
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _execute(node_id: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            result = await run_node(node_by_id[node_id], context)
        return node_id, result

    pending: set[asyncio.Task[tuple[str, dict[str, Any]]]] = set()
    scheduled: set[str] = set()

    def _ready() -> list[str]:
        return [
            node_id
            for node_id, edges in remaining.items()
            if node_id not in scheduled and node_id not in results and not edges
        ]

    def _skip(node_id: str, because: str) -> None:
        results[node_id] = {"ok": False, "skipped": True, "skipped_because": because}
        failed.add(node_id)

    for node_id in _ready():
        scheduled.add(node_id)
        pending.add(asyncio.create_task(_execute(node_id)))

    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            node_id, result = task.result()
            results[node_id] = result
            context[node_id] = result
            if not result.get("ok", False):
                failed.add(node_id)

        # Release dependents whose dependencies are all resolved; skip any whose
        # dependency failed.
        for other_id, edges in remaining.items():
            if other_id in results or other_id in scheduled:
                continue
            if edges & failed:
                blocker = next(iter(edges & failed))
                _skip(other_id, blocker)
                continue
            remaining[other_id] = edges - set(results)

        for node_id in _ready():
            scheduled.add(node_id)
            pending.add(asyncio.create_task(_execute(node_id)))

    # Anything still unresolved was transitively blocked by a failure.
    for node_id in remaining:
        if node_id not in results:
            blocker = next((d for d in deps[node_id] if d in failed), "upstream")
            _skip(node_id, blocker)

    return results
