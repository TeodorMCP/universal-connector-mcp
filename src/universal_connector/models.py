"""Normalized data model shared by every adapter, executor and tool.

The whole point of this project is that adapters translate wildly different API
descriptions (OpenAPI, GraphQL, gRPC, SOAP) into these protocol-agnostic types.
Everything downstream operates on `Operation` and never needs to know where it
came from.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Protocol(str, Enum):
    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    GRPC = "grpc"
    SOAP = "soap"


class ParameterLocation(str, Enum):
    """Where a parameter is placed when the request is built.

    REST uses path/query/header/cookie/body. GraphQL arguments and gRPC/SOAP
    message fields are normalized to ``body`` (they become part of the request
    payload), with protocol-specific hints kept in ``Operation.extra``.
    """

    PATH = "path"
    QUERY = "query"
    HEADER = "header"
    COOKIE = "cookie"
    BODY = "body"


class AuthType(str, Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2 = "oauth2"


class Parameter(BaseModel):
    """A single input to an operation."""

    name: str
    location: ParameterLocation = ParameterLocation.QUERY
    required: bool = False
    description: str | None = None
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    default: Any | None = None

    model_config = {"populate_by_name": True}

    def json_schema(self) -> dict[str, Any]:
        """JSON-schema fragment describing this parameter's value."""
        schema = dict(self.schema_) if self.schema_ else {"type": "string"}
        if self.description and "description" not in schema:
            schema["description"] = self.description
        if self.default is not None and "default" not in schema:
            schema["default"] = self.default
        return schema


class AuthScheme(BaseModel):
    """A security scheme an operation may require.

    ``credential_ref`` names the environment variable / keyring entry that holds
    the secret. Secrets themselves are never stored on the model.
    """

    type: AuthType = AuthType.NONE
    name: str | None = None  # header or query param name (api_key)
    location: ParameterLocation | None = None  # where api_key goes
    scheme: str | None = None  # e.g. "bearer", "basic"
    credential_ref: str | None = None
    # OAuth2 metadata (used in a later phase)
    token_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    flows: dict[str, Any] = Field(default_factory=dict)


class Operation(BaseModel):
    """A protocol-agnostic, executable API operation."""

    operation_id: str
    api_name: str
    protocol: Protocol
    method: str  # HTTP verb, "query"/"mutation", or RPC/SOAP action
    path: str  # URL template, GraphQL field, gRPC full method, or SOAP operation
    base_url: str
    summary: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    request_body_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    auth: list[AuthScheme] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    def input_schema(self) -> dict[str, Any]:
        """Build a JSON schema describing all inputs for this operation.

        Used both to describe the operation to the agent and to validate the
        ``params`` object passed to ``execute``.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            properties[param.name] = param.json_schema()
            if param.required:
                required.append(param.name)
        if self.request_body_schema is not None:
            properties["body"] = self.request_body_schema
            # A request body is required only if the schema says so implicitly;
            # we keep it optional here and let the upstream API validate.
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    def search_text(self) -> str:
        """Concatenated text used for fuzzy searching."""
        parts = [
            self.operation_id,
            self.method,
            self.path,
            self.summary or "",
            self.description or "",
            " ".join(self.tags),
        ]
        return " ".join(p for p in parts if p).lower()


class LoadedApi(BaseModel):
    """Metadata about an API that has been loaded into the registry."""

    name: str
    protocol: Protocol
    base_url: str
    title: str | None = None
    version: str | None = None
    spec_source: str | None = None
    operation_count: int = 0
    hosts: list[str] = Field(default_factory=list)
    auth_schemes: list[AuthScheme] = Field(default_factory=list)
