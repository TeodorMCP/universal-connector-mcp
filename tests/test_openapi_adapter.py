import pytest

from universal_connector.adapters.base import detect_protocol
from universal_connector.models import Protocol


async def test_load_openapi_registers_operations(service, openapi_spec_json):
    result = await service.load_api(openapi_spec_json, name="demo")
    assert result["protocol"] == "openapi"
    assert result["operation_count"] == 2
    assert result["base_url"] == "https://api.demo.test/v1"
    assert "api.demo.test" in result["hosts"]


async def test_ref_resolution_in_response_schema(service, openapi_spec_json):
    await service.load_api(openapi_spec_json, name="demo")
    op = service.get_operation("demo.getPet")
    # $ref to components/schemas/Pet should be inlined.
    assert op["response_schema"]["properties"]["id"]["type"] == "integer"
    assert op["response_schema"]["properties"]["name"]["type"] == "string"


async def test_input_schema_marks_required_path_param(service, openapi_spec_json):
    await service.load_api(openapi_spec_json, name="demo")
    op = service.get_operation("demo.getPet")
    schema = op["input_schema"]
    assert "petId" in schema["properties"]
    assert "petId" in schema["required"]
    assert "verbose" in schema["properties"]
    assert "verbose" not in schema.get("required", [])


async def test_security_schemes_detected(service, openapi_spec_json):
    await service.load_api(openapi_spec_json, name="demo")
    get_pet = service.get_operation("demo.getPet")
    create_pet = service.get_operation("demo.createPet")
    assert get_pet["auth_required"][0]["type"] == "api_key"
    assert create_pet["auth_required"][0]["type"] == "bearer"


async def test_search_finds_operations(service, openapi_spec_json):
    await service.load_api(openapi_spec_json, name="demo")
    hits = service.search_operations("create pet")
    assert hits
    assert hits[0]["operation_id"] == "demo.createPet"


async def test_duplicate_load_is_rejected(service, openapi_spec_json):
    from universal_connector.registry import ApiAlreadyLoadedError

    await service.load_api(openapi_spec_json, name="demo")
    with pytest.raises(ApiAlreadyLoadedError):
        await service.load_api(openapi_spec_json, name="demo")


async def test_unload_removes_operations(service, openapi_spec_json):
    await service.load_api(openapi_spec_json, name="demo")
    service.unload_api("demo")
    assert service.list_apis() == []


def test_detect_protocol_openapi(openapi_spec_json):
    assert detect_protocol(openapi_spec_json, "https://x/openapi.json") == Protocol.OPENAPI


def test_detect_protocol_graphql_sdl(graphql_sdl):
    assert detect_protocol(graphql_sdl, "schema.graphql") == Protocol.GRAPHQL


def test_detect_protocol_soap():
    wsdl = '<?xml version="1.0"?><definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"></definitions>'
    assert detect_protocol(wsdl, "service.wsdl") == Protocol.SOAP


def test_detect_protocol_grpc():
    assert detect_protocol("", "grpc://localhost:50051") == Protocol.GRPC
