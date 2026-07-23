"""Adapter interface plus protocol auto-detection and registry.

An adapter turns a raw spec (text) into a normalized `LoadedApi` and its list of
`Operation` objects. Detection picks the right adapter from the spec content and
source hint so callers can just say "load this URL".
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from universal_connector.models import LoadedApi, Operation, Protocol


class AdapterError(Exception):
    """Raised when a spec cannot be parsed by an adapter."""


class SpecAdapter(ABC):
    """Base class for all protocol adapters."""

    protocol: Protocol

    @abstractmethod
    def parse(
        self,
        content: str,
        source: str,
        name: str,
        base_url: str | None = None,
    ) -> tuple[LoadedApi, list[Operation]]:
        """Parse ``content`` into a `LoadedApi` and its operations.

        ``source`` is the original URL/path (used for base-URL inference).
        ``name`` namespaces the operations (``<name>.<operation>``).
        """
        raise NotImplementedError


def _looks_like_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _try_parse_structured(text: str) -> dict | None:
    """Parse JSON or YAML into a dict, or return None."""
    text = text.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        import yaml

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def detect_protocol(content: str, source: str = "") -> Protocol:
    """Best-effort detection of the spec protocol.

    Order matters: cheap source-hint checks first, then content inspection.
    """
    src = source.lower()

    if src.startswith("grpc://") or src.endswith(".proto"):
        return Protocol.GRPC
    if src.endswith(".wsdl"):
        return Protocol.SOAP
    if src.endswith(".graphql") or src.endswith(".gql"):
        return Protocol.GRAPHQL

    lowered = content.lstrip()[:4000].lower()

    # SOAP / WSDL is XML with the WSDL definitions element.
    if lowered.startswith("<") and ("wsdl" in lowered or "<definitions" in lowered):
        return Protocol.SOAP

    data = _try_parse_structured(content)
    if data is not None:
        if "openapi" in data or "swagger" in data:
            return Protocol.OPENAPI
        # GraphQL introspection JSON.
        if "__schema" in data or ("data" in data and isinstance(data.get("data"), dict)
                                  and "__schema" in data["data"]):
            return Protocol.GRAPHQL

    # GraphQL SDL heuristics.
    if "type query" in lowered or "schema {" in lowered or "__schema" in lowered:
        return Protocol.GRAPHQL

    if _looks_like_json(content):
        # Structured but unrecognized: assume OpenAPI-ish REST.
        return Protocol.OPENAPI

    raise AdapterError(
        "Could not detect API protocol from the spec. "
        "Pass an explicit protocol (openapi/graphql/grpc/soap)."
    )


def get_adapter(protocol: Protocol) -> SpecAdapter:
    """Return an adapter instance for ``protocol``.

    Adapters are imported lazily so optional dependencies (graphql-core,
    grpcio, zeep) are only required when actually used.
    """
    if protocol == Protocol.OPENAPI:
        from universal_connector.adapters.openapi import OpenAPIAdapter

        return OpenAPIAdapter()
    if protocol == Protocol.GRAPHQL:
        from universal_connector.adapters.graphql import GraphQLAdapter

        return GraphQLAdapter()
    if protocol == Protocol.GRPC:
        from universal_connector.adapters.grpc import GrpcAdapter

        return GrpcAdapter()
    if protocol == Protocol.SOAP:
        from universal_connector.adapters.soap import SoapAdapter

        return SoapAdapter()
    raise AdapterError(f"No adapter for protocol '{protocol}'.")
