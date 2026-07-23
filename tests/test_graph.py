"""Tests for the execute_graph DAG planner."""

import asyncio

import httpx
import pytest
import respx

from universal_connector.config import Config
from universal_connector.graph import GraphError, build_dependencies, run_graph
from universal_connector.tools import ConnectorService

# --- dependency inference & validation (pure planner) --------------------


def test_dependencies_inferred_from_refs():
    nodes = [
        {"id": "a", "operation_id": "x.op"},
        {"id": "b", "operation_id": "x.op", "params": {"v": "${a.data.id}"}},
    ]
    assert build_dependencies(nodes) == {"a": set(), "b": {"a"}}


def test_explicit_depends_on():
    nodes = [
        {"id": "a", "operation_id": "x.op"},
        {"id": "b", "operation_id": "x.op", "depends_on": ["a"]},
    ]
    assert build_dependencies(nodes)["b"] == {"a"}


def test_unknown_reference_rejected():
    nodes = [{"id": "a", "operation_id": "x.op", "params": {"v": "${ghost.id}"}}]
    with pytest.raises(GraphError, match="unknown node"):
        build_dependencies(nodes)


def test_duplicate_id_rejected():
    nodes = [{"id": "a", "operation_id": "x.op"}, {"id": "a", "operation_id": "x.op"}]
    with pytest.raises(GraphError, match="Duplicate"):
        build_dependencies(nodes)


def test_missing_operation_id_rejected():
    with pytest.raises(GraphError, match="operation_id"):
        build_dependencies([{"id": "a"}])


def test_cycle_detected():
    nodes = [
        {"id": "a", "operation_id": "x.op", "params": {"v": "${b.x}"}},
        {"id": "b", "operation_id": "x.op", "params": {"v": "${a.x}"}},
    ]
    with pytest.raises(GraphError, match="cycle"):
        build_dependencies(nodes)


# --- scheduling behavior (fake executor) ---------------------------------


def _recording_runner():
    """A run_node that records concurrency and returns ok results by node id."""
    state = {"in_flight": 0, "max_in_flight": 0, "order": []}

    async def run_node(node, context):
        state["in_flight"] += 1
        state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        state["order"].append(node["id"])
        await asyncio.sleep(0.02)
        state["in_flight"] -= 1
        return {"ok": True, "data": {"id": node["id"]}}

    return run_node, state


@pytest.mark.asyncio
async def test_independent_nodes_run_in_parallel():
    nodes = [
        {"id": "a", "operation_id": "x.op"},
        {"id": "b", "operation_id": "x.op"},
        {"id": "c", "operation_id": "x.op"},
    ]
    run_node, state = _recording_runner()
    results = await run_graph(nodes, run_node)
    assert all(results[i]["ok"] for i in ("a", "b", "c"))
    assert state["max_in_flight"] == 3


@pytest.mark.asyncio
async def test_dependency_forces_ordering():
    nodes = [
        {"id": "a", "operation_id": "x.op"},
        {"id": "b", "operation_id": "x.op", "params": {"v": "${a.data.id}"}},
    ]
    run_node, state = _recording_runner()
    await run_graph(nodes, run_node)
    assert state["order"] == ["a", "b"]
    assert state["max_in_flight"] == 1


@pytest.mark.asyncio
async def test_diamond_parallelizes_middle():
    # a -> {b, c} -> d : b and c must overlap.
    nodes = [
        {"id": "a", "operation_id": "x.op"},
        {"id": "b", "operation_id": "x.op", "params": {"v": "${a.data.id}"}},
        {"id": "c", "operation_id": "x.op", "params": {"v": "${a.data.id}"}},
        {"id": "d", "operation_id": "x.op", "params": {"v": "${b.data.id}", "w": "${c.data.id}"}},
    ]
    run_node, state = _recording_runner()
    results = await run_graph(nodes, run_node)
    assert set(results) == {"a", "b", "c", "d"}
    assert state["order"][0] == "a"
    assert state["order"][-1] == "d"
    assert state["max_in_flight"] == 2  # b and c overlap, a and d run alone


@pytest.mark.asyncio
async def test_failure_skips_dependents_but_not_independent_branch():
    async def run_node(node, context):
        if node["id"] == "bad":
            return {"ok": False, "error": "boom"}
        return {"ok": True, "data": {"id": node["id"]}}

    nodes = [
        {"id": "bad", "operation_id": "x.op"},
        {"id": "child", "operation_id": "x.op", "params": {"v": "${bad.data.id}"}},
        {"id": "grandchild", "operation_id": "x.op", "params": {"v": "${child.data.id}"}},
        {"id": "independent", "operation_id": "x.op"},
    ]
    results = await run_graph(nodes, run_node)
    assert results["bad"]["ok"] is False
    assert results["child"]["skipped"] is True
    assert results["child"]["skipped_because"] == "bad"
    assert results["grandchild"]["skipped"] is True
    assert results["independent"]["ok"] is True


@pytest.mark.asyncio
async def test_max_concurrency_respected():
    nodes = [{"id": f"n{i}", "operation_id": "x.op"} for i in range(6)]
    run_node, state = _recording_runner()
    await run_graph(nodes, run_node, max_concurrency=2)
    assert state["max_in_flight"] == 2


# --- integration through ConnectorService --------------------------------


@respx.mock
async def test_execute_graph_end_to_end(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 5, "name": "Rex"})
    )
    respx.get("https://api.demo.test/v1/pets/5").mock(
        return_value=httpx.Response(200, json={"id": 5, "name": "Rex detailed"})
    )

    results = await svc.execute_graph(
        [
            {"id": "first", "operation_id": "demo.getPet", "params": {"petId": 1}},
            {
                "id": "second",
                "operation_id": "demo.getPet",
                "params": {"petId": "${first.data.id}"},
            },
        ]
    )
    assert results["first"]["data"]["id"] == 5
    assert results["second"]["data"]["name"] == "Rex detailed"
