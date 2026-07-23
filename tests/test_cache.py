import httpx
import respx

from universal_connector.cache import ResponseCache
from universal_connector.config import Config
from universal_connector.tools import ConnectorService


def _service(**config_kwargs) -> ConnectorService:
    return ConnectorService(Config(allow_all_hosts=True, **config_kwargs))


@respx.mock
async def test_repeated_get_is_served_from_cache(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = _service(cache_ttl=60)
    await svc.load_api(openapi_spec_json, name="demo")

    route = respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Rex"})
    )

    first = await svc.execute("demo.getPet", {"petId": 1})
    second = await svc.execute("demo.getPet", {"petId": 1})

    assert route.call_count == 1
    assert "cached" not in first
    assert second["cached"] is True
    assert second["data"] == first["data"]


@respx.mock
async def test_fresh_bypasses_cache(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = _service(cache_ttl=60)
    await svc.load_api(openapi_spec_json, name="demo")

    route = respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    await svc.execute("demo.getPet", {"petId": 1})
    result = await svc.execute("demo.getPet", {"petId": 1}, fresh=True)

    assert route.call_count == 2
    assert "cached" not in result


@respx.mock
async def test_different_params_are_cached_separately(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = _service(cache_ttl=60)
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    respx.get("https://api.demo.test/v1/pets/2").mock(
        return_value=httpx.Response(200, json={"id": 2})
    )
    one = await svc.execute("demo.getPet", {"petId": 1})
    two = await svc.execute("demo.getPet", {"petId": 2})
    assert one["data"]["id"] == 1
    assert two["data"]["id"] == 2


@respx.mock
async def test_errors_are_not_cached(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = _service(cache_ttl=60)
    await svc.load_api(openapi_spec_json, name="demo")

    route = respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    await svc.execute("demo.getPet", {"petId": 1})
    await svc.execute("demo.getPet", {"petId": 1})
    assert route.call_count == 2


@respx.mock
async def test_mutation_is_not_cached_and_invalidates_api_reads(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    monkeypatch.setenv("DEMO_TOKEN", "t")
    svc = _service(cache_ttl=60)
    await svc.load_api(openapi_spec_json, name="demo")

    get_route = respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Rex"})
    )
    post_route = respx.post("https://api.demo.test/v1/pets").mock(
        return_value=httpx.Response(201, json={"id": 2})
    )

    await svc.execute("demo.getPet", {"petId": 1})
    await svc.execute("demo.createPet", {"body": {"name": "Buddy"}})
    await svc.execute("demo.createPet", {"body": {"name": "Buddy"}})
    # The POST ran twice (never cached), and it evicted the cached GET.
    assert post_route.call_count == 2
    await svc.execute("demo.getPet", {"petId": 1})
    assert get_route.call_count == 2


async def test_cache_disabled_with_zero_ttl(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = _service(cache_ttl=0)
    assert svc.cache.enabled is False


def test_cache_ttl_expiry(monkeypatch):
    cache = ResponseCache(ttl_seconds=60)
    cache.set("demo.op|abc", {"ok": True})

    now = [0.0]
    monkeypatch.setattr("universal_connector.cache.time.monotonic", lambda: now[0])
    cache.set("demo.op|abc", {"ok": True})
    now[0] = 59.0
    assert cache.get("demo.op|abc") is not None
    now[0] = 61.0
    assert cache.get("demo.op|abc") is None


def test_cache_invalidate_api_only_touches_that_api():
    cache = ResponseCache(ttl_seconds=60)
    cache.set("github.repos|k1", {"ok": True})
    cache.set("stripe.charges|k2", {"ok": True})
    cache.invalidate_api("github")
    assert cache.get("github.repos|k1") is None
    assert cache.get("stripe.charges|k2") is not None
