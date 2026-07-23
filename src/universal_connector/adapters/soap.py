"""SOAP/WSDL adapter (via zeep).

Enumerates every operation across the WSDL's services/ports. SOAP request types
are deeply nested XML schemas, so each operation exposes a single ``body`` object
parameter (with the human-readable zeep signature in its description) rather than
trying to flatten the whole XSD into JSON schema.
"""

from __future__ import annotations

import ipaddress
import socket
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
    """Always load the main WSDL from local content.

    The content was already fetched through the SSRF-guarded spec reader, so we
    spill it to a temp file rather than handing zeep a URL to re-fetch (which
    would bypass the guard). Local file sources are used directly.
    """
    if source.startswith(("http://", "https://")):
        tmp = Path(tempfile.gettempdir()) / "ucmcp_soap.wsdl"
        tmp.write_text(content, encoding="utf-8")
        return str(tmp)
    if Path(source).exists():
        return source
    tmp = Path(tempfile.gettempdir()) / "ucmcp_soap.wsdl"
    tmp.write_text(content, encoding="utf-8")
    return str(tmp)


def _guarded_transport():
    """A zeep Transport whose session blocks private/internal addresses.

    WSDL/XSD ``import`` directives make zeep fetch further documents; without
    this, those fetches would skip the security guard entirely (SSRF vector).
    """
    import requests
    from requests.adapters import HTTPAdapter
    from zeep import Transport

    def _blocked(host: str) -> bool:
        try:
            infos = socket.getaddrinfo(host, None, 0, socket.SOCK_STREAM)
        except socket.gaierror:
            return False
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return True
        return False

    class _GuardedAdapter(HTTPAdapter):
        def send(self, request, *args, **kwargs):  # noqa: ANN001, ANN002
            host = urlsplit(request.url).hostname or ""
            if _blocked(host):
                raise AdapterError(
                    f"Blocked SOAP import to private/internal host '{host}' (SSRF protection)."
                )
            return super().send(request, *args, **kwargs)

    session = requests.Session()
    adapter = _GuardedAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return Transport(session=session)


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
            client = Client(location, transport=_guarded_transport())
        except AdapterError:
            raise
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
