"""GraphQL adapter.

Accepts either an introspection result (JSON) or SDL text and emits one
`Operation` per top-level Query/Mutation field. Argument types are converted to
JSON schema for the agent, and a default selection set is precomputed so the
executor can issue a valid query without re-parsing the schema.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from universal_connector.adapters.base import AdapterError, SpecAdapter
from universal_connector.models import (
    AuthScheme,
    AuthType,
    LoadedApi,
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
)

_SCALAR_JSON = {
    "Int": {"type": "integer"},
    "Float": {"type": "number"},
    "String": {"type": "string"},
    "Boolean": {"type": "boolean"},
    "ID": {"type": "string"},
}
_MAX_SELECTION_DEPTH = 3


def _build_schema(content: str):
    try:
        from graphql import build_client_schema, build_schema
    except ImportError as exc:  # noqa: BLE001
        raise AdapterError(
            "GraphQL support requires the 'graphql-core' package. "
            "Install with: pip install 'universal-connector-mcp[graphql]'"
        ) from exc

    content = content.strip()
    # Try introspection JSON first.
    try:
        data = json.loads(content)
        introspection = data.get("data", data) if isinstance(data, dict) else None
        if isinstance(introspection, dict) and "__schema" in introspection:
            return build_client_schema(introspection)
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to SDL.
    try:
        return build_schema(content)
    except Exception as exc:  # noqa: BLE001
        raise AdapterError(f"Could not parse GraphQL schema: {exc}") from exc


def _unwrap(gql_type):
    """Strip NonNull/List wrappers to reach the named type."""
    from graphql import GraphQLList, GraphQLNonNull

    while isinstance(gql_type, (GraphQLNonNull, GraphQLList)):
        gql_type = gql_type.of_type
    return gql_type


def _type_to_json_schema(gql_type) -> dict[str, Any]:
    from graphql import GraphQLEnumType, GraphQLList, GraphQLNonNull, GraphQLScalarType

    if isinstance(gql_type, GraphQLNonNull):
        return _type_to_json_schema(gql_type.of_type)
    if isinstance(gql_type, GraphQLList):
        return {"type": "array", "items": _type_to_json_schema(gql_type.of_type)}
    named = _unwrap(gql_type)
    if isinstance(named, GraphQLScalarType):
        return dict(_SCALAR_JSON.get(named.name, {"type": "string"}))
    if isinstance(named, GraphQLEnumType):
        return {"type": "string", "enum": list(named.values.keys())}
    # Input object types: represent as generic object.
    return {"type": "object"}


def _build_selection(gql_type, depth: int = 0) -> str:
    """Generate a default selection set string for object/interface return types."""
    from graphql import (
        GraphQLInterfaceType,
        GraphQLObjectType,
        GraphQLUnionType,
    )

    named = _unwrap(gql_type)
    if isinstance(named, GraphQLUnionType):
        return "{ __typename }"
    if not isinstance(named, (GraphQLObjectType, GraphQLInterfaceType)):
        return ""  # scalar / enum -> leaf, no selection

    if depth >= _MAX_SELECTION_DEPTH:
        return "{ __typename }"

    parts: list[str] = []
    for fname, field in named.fields.items():
        # Skip fields that require arguments to keep the default query valid.
        if field.args:
            continue
        sub = _build_selection(field.type, depth + 1)
        parts.append(f"{fname} {sub}".strip())
    if not parts:
        return "{ __typename }"
    return "{ " + " ".join(parts) + " }"


class GraphQLAdapter(SpecAdapter):
    protocol = Protocol.GRAPHQL

    def parse(
        self,
        content: str,
        source: str,
        name: str,
        base_url: str | None = None,
    ) -> tuple[LoadedApi, list[Operation]]:
        schema = _build_schema(content)

        resolved_base = base_url or (source if source.startswith("http") else "")
        if not resolved_base:
            raise AdapterError(
                "GraphQL requires a base URL (the endpoint). Pass base_url explicitly."
            )
        resolved_base = resolved_base.rstrip("/")

        operations: list[Operation] = []
        default_auth = AuthScheme(
            type=AuthType.BEARER,
            scheme="bearer",
            credential_ref=None,
        )

        for op_type, root in (("query", schema.query_type), ("mutation", schema.mutation_type)):
            if root is None:
                continue
            for field_name, field in root.fields.items():
                operations.append(
                    self._build_operation(
                        op_type=op_type,
                        field_name=field_name,
                        field=field,
                        api_name=name,
                        base_url=resolved_base,
                        default_auth=default_auth,
                    )
                )

        host = urlsplit(resolved_base).hostname
        loaded = LoadedApi(
            name=name,
            protocol=Protocol.GRAPHQL,
            base_url=resolved_base,
            title=name,
            spec_source=source,
            hosts=[host.lower()] if host else [],
            auth_schemes=[default_auth],
        )
        return loaded, operations

    def _build_operation(
        self,
        *,
        op_type: str,
        field_name: str,
        field,
        api_name: str,
        base_url: str,
        default_auth: AuthScheme,
    ) -> Operation:
        parameters: list[Parameter] = []
        arg_types: dict[str, str] = {}
        from graphql import GraphQLNonNull

        for arg_name, arg in field.args.items():
            parameters.append(
                Parameter(
                    name=arg_name,
                    location=ParameterLocation.BODY,
                    required=isinstance(arg.type, GraphQLNonNull),
                    description=arg.description,
                    schema=_type_to_json_schema(arg.type),
                )
            )
            arg_types[arg_name] = str(arg.type)

        selection = _build_selection(field.type)
        return_schema = _type_to_json_schema(field.type)

        return Operation(
            operation_id=f"{api_name}.{field_name}",
            api_name=api_name,
            protocol=Protocol.GRAPHQL,
            method=op_type,
            path=field_name,
            base_url=base_url,
            summary=field.description,
            description=field.description,
            parameters=parameters,
            response_schema=return_schema,
            auth=[default_auth],
            extra={
                "operation_type": op_type,
                "field_name": field_name,
                "arg_types": arg_types,
                "default_selection": selection,
            },
        )
