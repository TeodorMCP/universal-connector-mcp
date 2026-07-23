import httpx
import respx

from universal_connector.config import Config
from universal_connector.tools import ConnectorService, _extract_path

DATA = {
    "total_count": 3,
    "items": [
        {"id": 1, "name": "a", "owner": {"login": "x"}},
        {"id": 2, "name": "b", "owner": {"login": "y"}},
    ],
    "nested": {"deep": {"value": 42}},
}


def test_extract_simple_and_nested_paths():
    assert _extract_path(DATA, "total_count") == 3
    assert _extract_path(DATA, "nested.deep.value") == 42
    assert _extract_path(DATA, "items.0.name") == "a"


def test_extract_wildcard_over_lists_and_dicts():
    assert _extract_path(DATA, "items.*.name") == ["a", "b"]
    assert _extract_path(DATA, "items.*.owner.login") == ["x", "y"]
    assert _extract_path(DATA, "nested.*.value") == {"deep": 42}


def test_extract_missing_paths_return_none():
    assert _extract_path(DATA, "no.such.path") is None
    assert _extract_path(DATA, "items.9.name") is None
    assert _extract_path(DATA, "total_count.oops") is None


@respx.mock
async def test_execute_with_extract_returns_only_requested_fields(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(
            200, json={"id": 1, "name": "Rex", "big_blob": "x" * 500, "tags": ["dog", "good"]}
        )
    )
    result = await svc.execute("demo.getPet", {"petId": 1}, extract=["name", "tags.0"])

    assert result["ok"] is True
    assert result["extracted"] is True
    assert result["data"] == {"name": "Rex", "tags.0": "dog"}
    assert "big_blob" not in str(result["data"])


@respx.mock
async def test_chained_step_extract(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 7, "name": "Rex"})
    )

    results = await svc.execute_chained(
        [{"operation_id": "demo.getPet", "params": {"petId": 1}, "extract": ["id"]}]
    )
    assert results[0]["result"]["data"] == {"id": 7}
