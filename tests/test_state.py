import json

from universal_connector.config import Config
from universal_connector.tools import ConnectorService


def _service(tmp_path, **kwargs) -> ConnectorService:
    return ConnectorService(
        Config(allow_all_hosts=True, state_file=str(tmp_path / "state.json"), **kwargs)
    )


async def test_loaded_api_survives_restart(tmp_path, openapi_spec_json):
    spec_file = tmp_path / "demo.json"
    spec_file.write_text(openapi_spec_json, encoding="utf-8")

    first = _service(tmp_path)
    await first.load_api(str(spec_file), name="demo")
    assert (tmp_path / "state.json").exists()

    # "Restart": a brand-new service instance restores from the state file.
    second = _service(tmp_path)
    assert second.list_apis() == []
    restored = await second.restore_state()
    assert restored == ["demo"]
    assert second.registry.has_api("demo")
    # Restored operations are actually callable metadata, not stubs.
    assert second.get_operation("demo.getPet")["method"] == "GET"


async def test_unload_removes_from_state(tmp_path, openapi_spec_json):
    spec_file = tmp_path / "demo.json"
    spec_file.write_text(openapi_spec_json, encoding="utf-8")

    svc = _service(tmp_path)
    await svc.load_api(str(spec_file), name="demo")
    svc.unload_api("demo")

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["apis"] == []
    assert await _service(tmp_path).restore_state() == []


async def test_raw_spec_content_is_not_persisted(tmp_path, openapi_spec_json):
    svc = _service(tmp_path)
    await svc.load_api(openapi_spec_json, name="demo")  # raw JSON text, not a path
    # Nothing reloadable -> no state entry (file may not even exist).
    state_path = tmp_path / "state.json"
    if state_path.exists():
        assert json.loads(state_path.read_text(encoding="utf-8"))["apis"] == []


async def test_persistence_disabled_without_state_file(tmp_path, openapi_spec_json):
    spec_file = tmp_path / "demo.json"
    spec_file.write_text(openapi_spec_json, encoding="utf-8")

    svc = ConnectorService(Config(allow_all_hosts=True, state_file=None))
    await svc.load_api(str(spec_file), name="demo")
    assert not (tmp_path / "state.json").exists()
    assert await svc.restore_state() == []


async def test_restore_keeps_unloadable_entries(tmp_path, openapi_spec_json):
    spec_file = tmp_path / "demo.json"
    spec_file.write_text(openapi_spec_json, encoding="utf-8")

    svc = _service(tmp_path)
    await svc.load_api(str(spec_file), name="demo")

    # Simulate the spec becoming temporarily unavailable.
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["apis"].append({"name": "ghost", "spec": str(tmp_path / "missing.json")})
    state_path.write_text(json.dumps(state), encoding="utf-8")

    second = _service(tmp_path)
    restored = await second.restore_state()
    assert restored == ["demo"]
    # The failed entry must remain remembered for the next restart.
    assert "ghost" in second._persist


async def test_corrupt_state_file_is_ignored(tmp_path):
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    svc = _service(tmp_path)
    assert await svc.restore_state() == []
