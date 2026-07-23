import httpx
import respx

from universal_connector.config import Config
from universal_connector.tools import ConnectorService


@respx.mock
async def test_execute_chained_passes_data_between_steps(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 7, "name": "Rex"})
    )
    second = respx.get("https://api.demo.test/v1/pets/7").mock(
        return_value=httpx.Response(200, json={"id": 7, "name": "Rex full"})
    )

    results = await svc.execute_chained(
        [
            {"operation_id": "demo.getPet", "params": {"petId": 1}, "save_as": "first"},
            {"operation_id": "demo.getPet", "params": {"petId": "${first.data.id}"}},
        ]
    )

    assert len(results) == 2
    assert results[0]["result"]["data"]["id"] == 7
    assert second.called
    assert results[1]["result"]["data"]["name"] == "Rex full"


@respx.mock
async def test_chain_stops_on_error(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )

    results = await svc.execute_chained(
        [
            {"operation_id": "demo.getPet", "params": {"petId": 1}},
            {"operation_id": "demo.getPet", "params": {"petId": 2}},
        ]
    )
    # Second step should not run because the first failed.
    assert len(results) == 1


@respx.mock
async def test_parallel_group_runs_concurrently_and_feeds_next_step(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    import asyncio

    in_flight = 0
    max_in_flight = 0

    async def slow_response(request):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        pet_id = int(str(request.url.path).rsplit("/", 1)[-1])
        return httpx.Response(200, json={"id": pet_id, "name": f"pet{pet_id}"})

    respx.get(url__regex=r"https://api\.demo\.test/v1/pets/\d+").mock(side_effect=slow_response)

    results = await svc.execute_chained(
        [
            [
                {"operation_id": "demo.getPet", "params": {"petId": 1}, "save_as": "a"},
                {"operation_id": "demo.getPet", "params": {"petId": 2}, "save_as": "b"},
            ],
            {"operation_id": "demo.getPet", "params": {"petId": "${b.data.id}"}},
        ]
    )

    assert max_in_flight == 2, "parallel group steps must overlap in time"
    assert len(results) == 3
    assert results[0]["step"] == "a"
    assert results[1]["step"] == "b"
    assert results[2]["result"]["data"]["id"] == 2


@respx.mock
async def test_parallel_group_failure_stops_chain(openapi_spec_json, monkeypatch):
    monkeypatch.setenv("DEMO_APIKEY", "k")
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(openapi_spec_json, name="demo")

    respx.get("https://api.demo.test/v1/pets/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    respx.get("https://api.demo.test/v1/pets/2").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )

    results = await svc.execute_chained(
        [
            [
                {"operation_id": "demo.getPet", "params": {"petId": 1}},
                {"operation_id": "demo.getPet", "params": {"petId": 2}},
            ],
            {"operation_id": "demo.getPet", "params": {"petId": 3}},
        ]
    )
    # Both group results reported, but the chain stops before the third step.
    assert len(results) == 2
    assert results[1]["result"]["ok"] is False
