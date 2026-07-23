import json

import pytest

from universal_connector.config import Config
from universal_connector.tools import ConnectorService

OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Demo API", "version": "1.0.0"},
    "servers": [{"url": "https://api.demo.test/v1"}],
    "components": {
        "securitySchemes": {
            "apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "bearerAuth": {"type": "http", "scheme": "bearer"},
        },
        "schemas": {
            "Pet": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
            }
        },
    },
    "paths": {
        "/pets/{petId}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet by id",
                "tags": ["pets"],
                "security": [{"apiKey": []}],
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    },
                    {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        }
                    }
                },
            }
        },
        "/pets": {
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "tags": ["pets"],
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Pet"}
                        }
                    }
                },
                "responses": {"201": {"description": "created"}},
            }
        },
    },
}

GRAPHQL_SDL = """
type Query {
  user(id: ID!): User
  users(limit: Int): [User]
}
type Mutation {
  createUser(name: String!, email: String): User
}
type User {
  id: ID!
  name: String
  email: String
  posts: [Post]
}
type Post {
  id: ID!
  title: String
}
"""


@pytest.fixture
def openapi_spec_json() -> str:
    return json.dumps(OPENAPI_SPEC)


@pytest.fixture
def graphql_sdl() -> str:
    return GRAPHQL_SDL


@pytest.fixture
def service() -> ConnectorService:
    return ConnectorService(Config(allow_all_hosts=True))
