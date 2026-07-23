import httpx
import respx

from universal_connector.catalog import GURU_LIST_URL, Catalog
from universal_connector.tools import ConnectorService

GURU_LISTING = {
    "nasa.gov:apod": {
        "preferred": "1.0.0",
        "versions": {
            "1.0.0": {
                "swaggerUrl": "https://api.apis.guru/v2/specs/nasa.gov/apod/1.0.0/swagger.json",
                "info": {
                    "title": "NASA APOD",
                    "description": "Astronomy Picture of the Day. " + "x" * 300,
                    "x-apisguru-categories": ["media", "open_data"],
                },
            }
        },
    },
    "broken.example": {"preferred": "1.0", "versions": {}},
}


def test_curated_search_matches_by_tag_and_name():
    catalog = Catalog()
    results = catalog.search_curated("weather forecast")
    assert results
    assert results[0]["name"] == "open_meteo"
    assert results[0]["source"] == "curated"
    assert results[0]["spec"].startswith("https://")


def test_curated_search_no_match_returns_empty():
    catalog = Catalog()
    assert catalog.search_curated("quantum blockchain toaster") == []


def test_curated_graphql_entry_carries_protocol_and_base_url():
    catalog = Catalog()
    results = catalog.search_curated("countries graphql")
    assert results[0]["protocol"] == "graphql"
    assert results[0]["base_url"] == "https://countries.trevorblades.com/"


@respx.mock
async def test_directory_search_merges_apis_guru_results():
    respx.get(GURU_LIST_URL).mock(return_value=httpx.Response(200, json=GURU_LISTING))
    catalog = Catalog()

    results = await catalog.search("nasa astronomy picture", limit=5)

    assert len(results) == 1
    entry = results[0]
    assert entry["source"] == "apis.guru"
    assert entry["name"] == "nasa_gov_apod"
    assert entry["spec"].endswith("swagger.json")
    # Long directory descriptions are truncated to keep results compact.
    assert len(entry["description"]) < 300
    assert entry["description"].endswith("...")


@respx.mock
async def test_directory_is_fetched_once_and_cached():
    route = respx.get(GURU_LIST_URL).mock(return_value=httpx.Response(200, json=GURU_LISTING))
    catalog = Catalog()

    await catalog.search("nasa")
    await catalog.search("apod")

    assert route.call_count == 1


@respx.mock
async def test_directory_failure_still_returns_curated_results():
    respx.get(GURU_LIST_URL).mock(return_value=httpx.Response(503))
    catalog = Catalog()

    results = await catalog.search("github repositories")

    assert results
    assert all(r["source"] == "curated" for r in results)


async def test_service_search_catalog_adds_load_hint(service: ConnectorService):
    results = await service.search_catalog("weather", include_directory=False)
    assert results
    assert "load_api" in results[0]["hint"]
