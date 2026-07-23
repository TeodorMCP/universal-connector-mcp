import httpx
import respx

from universal_connector.config import Config
from universal_connector.executor.graphql import GraphQLExecutor
from universal_connector.tools import ConnectorService


async def test_graphql_load_and_schema(service, graphql_sdl):
    result = await service.load_api(
        graphql_sdl, name="social", base_url="https://api.social.test/graphql", protocol="graphql"
    )
    assert result["protocol"] == "graphql"
    assert result["operation_count"] == 3
    op = service.get_operation("social.user")
    assert "id" in op["input_schema"]["properties"]
    assert "id" in op["input_schema"]["required"]


async def test_graphql_query_building(service, graphql_sdl):
    await service.load_api(
        graphql_sdl, name="social", base_url="https://api.social.test/graphql", protocol="graphql"
    )
    op = service.registry.get_operation("social.user")
    query = GraphQLExecutor()._build_query(op, {"id": "1"}, None)
    assert query.startswith("query ($id: ID!)")
    assert "user(id: $id)" in query
    assert "posts" in query  # nested selection auto-generated


async def test_graphql_field_selection_override(service, graphql_sdl):
    await service.load_api(
        graphql_sdl, name="social", base_url="https://api.social.test/graphql", protocol="graphql"
    )
    op = service.registry.get_operation("social.user")
    query = GraphQLExecutor()._build_query(op, {"id": "1"}, "id name")
    assert "{ id name }" in query
    assert "posts" not in query


@respx.mock
async def test_graphql_execute(graphql_sdl):
    svc = ConnectorService(Config(allow_all_hosts=True))
    await svc.load_api(
        graphql_sdl, name="social", base_url="https://api.social.test/graphql", protocol="graphql"
    )
    route = respx.post("https://api.social.test/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"id": "1", "name": "Ada"}}})
    )
    result = await svc.execute("social.user", {"id": "1", "fields": "id name"})
    assert result["ok"] is True
    assert result["data"]["data"]["user"]["name"] == "Ada"
    assert route.called
