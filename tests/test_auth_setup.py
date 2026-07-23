from universal_connector.config import Config
from universal_connector.tools import ConnectorService


async def test_load_api_reports_missing_credentials(openapi_spec_json, monkeypatch):
    monkeypatch.delenv("DEMO_APIKEY", raising=False)
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    svc = ConnectorService(Config(allow_all_hosts=True))
    info = await svc.load_api(openapi_spec_json, name="demo")

    assert info["auth_setup"], "auth schemes must be described"
    assert all(entry["configured"] is False for entry in info["auth_setup"])
    # The hint must name a concrete env var the user can copy-paste.
    assert "DEMO_" in info["hint"]
    assert "env" in info["hint"]
    # Env var suggestions follow the documented convention.
    api_key = next(e for e in info["auth_setup"] if e["type"] == "api_key")
    assert "DEMO_TOKEN" in api_key["env_vars"] or "DEMO_API_KEY" in api_key["env_vars"]


async def test_load_api_reports_configured_credentials(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "secret")
    svc = ConnectorService(Config(allow_all_hosts=True))
    info = await svc.load_api(openapi_spec_json, name="demo")

    assert all(entry["configured"] for entry in info["auth_setup"])
    # With credentials in place the hint goes back to the normal workflow.
    assert info["hint"].startswith("Use search_operations")
    # Secret values must never appear in the response.
    assert "secret" not in str(info)


async def test_auth_setup_dedupes_scheme_types(openapi_spec_json):
    svc = ConnectorService(Config(allow_all_hosts=True))
    info = await svc.load_api(openapi_spec_json, name="demo")
    types = [entry["type"] for entry in info["auth_setup"]]
    assert len(types) == len(set(types))
