import httpx
import respx

from universal_connector.config import Config
from universal_connector.tools import ConnectorService


@respx.mock
async def test_execute_injects_api_key_and_parses_response(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "secret-key")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    route = respx.get("https://api.demo.test/v1/pets/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "name": "Rex"})
    )
    result = await svc.execute("demo.getPet", {"petId": 42, "verbose": True})

    assert result["ok"] is True
    assert result["status"] == 200
    assert result["data"] == {"id": 42, "name": "Rex"}
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-API-Key"] == "secret-key"
    assert "verbose=true" in str(request.url).lower()


@respx.mock
async def test_execute_blocked_host_is_reported(openapi_spec_json):
    # allow_all_hosts=False and we never register the host -> blocked.
    svc = ConnectorService(Config(allow_all_hosts=False, allowed_hosts=["other.test"]))
    # Manually add an operation whose host is not allowed.
    await svc.load_api(openapi_spec_json, name="demo")
    # demo host got registered by load; deny it explicitly.
    svc.guard._registered.discard("api.demo.test")

    result = await svc.execute("demo.getPet", {"petId": 1})
    assert result["ok"] is False
    assert "not allowed" in result["error"]


@respx.mock
async def test_error_status_marks_not_ok(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")
    respx.get("https://api.demo.test/v1/pets/99").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )
    result = await svc.execute("demo.getPet", {"petId": 99})
    assert result["ok"] is False
    assert result["status"] == 404


@respx.mock
async def test_audit_log_records_calls(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")
    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    await svc.execute("demo.getPet", {"petId": 1})
    entries = svc.audit_log()
    assert entries
    assert entries[-1]["operation_id"] == "demo.getPet"
    assert entries[-1]["host"] == "api.demo.test"
    assert entries[-1]["status"] == 200
