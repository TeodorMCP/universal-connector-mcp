"""SOAP/WSDL adapter (via zeep).

Enumerates every operation across the WSDL's services/ports. SOAP request types
are deeply nested XML schemas, so each operation exposes a single ``body`` object
parameter (with the human-readable zeep signature in its description) rather than
trying to flatten the whole XSD into JSON schema.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from universal_connector.adapters.base import AdapterError, SpecAdapter
from universal_connector.models import (
    LoadedApi,
    Operation,
    Parameter,
    ParameterLocation,
    Protocol,
)


def _wsdl_location(content: str, source: str) -> str:
    """zeep loads from a URL/path; if we only have raw XML, spill to a temp file."""
    if source.startswith("http") or Path(source).exists():
        return source
    tmp = Path(tempfile.gettempdir()) / "ucmcp_soap.wsdl"
    tmp.write_text(content, encoding="utf-8")
    return str(tmp)


class SoapAdapter(SpecAdapter):
    protocol = Protocol.SOAP

    def parse(
        self,
        content: str,
        source: str,
        name: str,
        base_url: str | None = None,
    ) -> tuple[LoadedApi, list[Operation]]:
        try:
            from zeep import Client
        except ImportError as exc:  # noqa: BLE001
            raise AdapterError(
                "SOAP support requires the 'zeep' package. "
                "Install with: pip install 'universal-connector-mcp[soap]'"
            ) from exc

        location = _wsdl_location(content, source)
        try:
            client = Client(location)
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(f"Could not parse WSDL: {exc}") from exc

        operations: list[Operation] = []
        endpoint = base_url

        for service_name, service in client.wsdl.services.items():
            for port_name, port in service.ports.items():
                address = port.binding_options.get("address", "")
                endpoint = base_url or address or endpoint
                binding = port.binding
                for op_name, op in binding._operations.items():
                    try:
                        signature = op.input.signature()
                    except Exception:  # noqa: BLE001
                        signature = ""
                    operations.append(
                        Operation(
                            operation_id=f"{name}.{op_name}",
                            api_name=name,
                            protocol=Protocol.SOAP,
                            method="POST",
                            path=op_name,
                            base_url=endpoint or address,
                            summary=f"SOAP operation {op_name}",
                            description=f"Signature: {signature}" if signature else None,
                            parameters=[
                                Parameter(
                                    name="body",
                                    location=ParameterLocation.BODY,
                                    required=True,
                                    description=f"Arguments for {op_name}. {signature}",
                                    schema={"type": "object"},
                                )
                            ],
                            extra={
                                "wsdl": location,
                                "service": service_name,
                                "port": port_name,
                                "operation": op_name,
                            },
                        )
                    )

        if not endpoint:
            raise AdapterError("Could not determine SOAP endpoint; pass base_url.")

        host = urlsplit(endpoint).hostname
        loaded = LoadedApi(
            name=name,
            protocol=Protocol.SOAP,
            base_url=endpoint,
            title=name,
            spec_source=source,
            hosts=[host.lower()] if host else [],
        )
        return loaded, operations
