"""FastMCP server exposing the universal connector meta-tools.

Run with ``universal-connector-mcp`` (stdio transport) after installing the
package, or ``python -m universal_connector.server``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from universal_connector.adapters.base import AdapterError
from universal_connector.config import Config
from universal_connector.registry import (
    ApiAlreadyLoadedError,
    ApiNotFoundError,
    OperationNotFoundError,
)
from universal_connector.security.guard import SecurityError
from universal_connector.tools import ConnectorService

INSTRUCTIONS = """\
Universal API Connector: one server that talks to any API (OpenAPI/REST, GraphQL, gRPC, SOAP).

Typical workflow:
1. search_catalog(query=...) - find a ready-to-load public API (curated list + APIs.guru, 2500+ specs). Skip if you already have a spec URL/file.
2. load_api(spec=...) - register the API; pass name/base_url/protocol from the catalog result when present.
3. search_operations(query=...) - discover operations; then get_operation(operation_id=...) for exact input schemas when parameters are unclear.
4. execute(operation_id=..., params=...) - call it. Use extract=["path.to.field"] to receive only the fields you need instead of a full response.
5. For multi-call workflows prefer ONE execute_chained call: steps pipe results via ${save_as.path} references, and a nested list of steps runs in parallel.

Managing APIs is conversational: the user says "connect X" / "forget X" / "what is
connected?" and you call load_api / unload_api / list_apis. If load_api reports
auth_setup entries with configured=false, tell the user the exact env var name to add
to the "env" block of their MCP config (and to restart the client) - never ask for
secret values in chat.

Notes:
- Credentials come from environment variables (<API>_TOKEN / <API>_API_KEY etc.); never pass secrets in params.
- Outbound hosts are allowlisted (loaded spec hosts + UCMCP_ALLOWED_HOSTS). A blocked call returns a security error, not silence.
- Successful GET/query results are cached briefly; pass fresh=true when you need live data.
- Loaded APIs are remembered across restarts in a local, human-readable state file
  (UCMCP_STATE_FILE, default ~/.universal-connector-mcp/state.json). It stores spec
  locations only - never credentials, requests or responses - and everything stays on
  this machine. unload_api forgets an API; UCMCP_STATE_FILE=off disables persistence.
  If the user asks what this server stores or where, tell them exactly this.
"""

mcp = FastMCP("universal-connector", instructions=INSTRUCTIONS)
service = ConnectorService()


def _error(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
async def load_api(
    spec: str,
    name: str | None = None,
    base_url: str | None = None,
    protocol: str | None = None,
) -> dict[str, Any]:
    """Load an API into the connector from a spec URL, file path, or raw content.

    The protocol (openapi/graphql/grpc/soap) is auto-detected unless given.
    After loading, use `search_operations` to discover operations.

    Args:
        spec: URL, local file path, or raw spec text.
        name: Optional short name used to namespace operations (``<name>.<op>``).
        base_url: Override the API base URL if the spec omits or misstates it.
        protocol: Force a protocol instead of auto-detecting.
    """
    try:
        return await service.load_api(spec, name=name, base_url=base_url, protocol=protocol)
    except (AdapterError, ApiAlreadyLoadedError, ValueError, OSError) as exc:
        return _error(exc)


@mcp.tool()
def list_apis() -> list[dict[str, Any]]:
    """List all currently loaded APIs with their protocol, base URL and size."""
    return service.list_apis()


@mcp.tool()
def unload_api(name: str) -> dict[str, Any]:
    """Remove a previously loaded API and free its operations."""
    try:
        return service.unload_api(name)
    except ApiNotFoundError as exc:
        return _error(exc)


@mcp.tool()
def search_operations(query: str, api: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Fuzzy-search operations across loaded APIs.

    Returns operation ids you can pass to `get_operation` or `execute`.

    Args:
        query: Keywords to search for (matched against id, path, summary, tags).
        api: Restrict the search to a single loaded API by name.
        limit: Maximum number of results.
    """
    return service.search_operations(query, api=api, limit=limit)


@mcp.tool()
def get_operation(operation_id: str) -> dict[str, Any]:
    """Get the full input schema, response schema and auth requirements of one operation."""
    try:
        return service.get_operation(operation_id)
    except OperationNotFoundError as exc:
        return _error(exc)


@mcp.tool()
async def execute(
    operation_id: str,
    params: dict[str, Any] | None = None,
    extract: list[str] | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    """Execute a loaded operation.

    Credentials are injected from environment variables / keyring, the target
    host must be allowed by the security policy, and the response is size-capped.

    Args:
        operation_id: Id from `search_operations` (e.g. ``github.repos_get``).
        params: Object matching the operation's ``input_schema`` (path/query/header
            values plus an optional ``body``).
        extract: Optional list of dotted paths to keep from the response data,
            discarding everything else (saves context). ``*`` fans out over
            arrays: e.g. ``["items.*.name", "total_count"]``.
        fresh: Bypass the short-lived response cache for GET/query operations.
    """
    try:
        return await service.execute(operation_id, params or {}, extract=extract, fresh=fresh)
    except (OperationNotFoundError, SecurityError, ValueError) as exc:
        return _error(exc)


@mcp.tool()
async def execute_chained(
    steps: list[dict[str, Any] | list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Execute a sequence of operations in one call, passing data between steps.

    Each step is an object ``{"operation_id", "params"?, "save_as"?, "extract"?,
    "fresh"?, "stop_on_error"?}``. A later step can reference an earlier result
    with ``${save_as.path.to.value}`` inside its params (e.g. ``${step1.data.id}``).

    A nested LIST of step objects forms a parallel group: those steps run
    concurrently (e.g. query three APIs at once) and later steps can reference
    all of their results. Use `extract` per step to keep responses small.

    Args:
        steps: Ordered list of step objects and/or parallel groups (lists of
            step objects).
    """
    try:
        return await service.execute_chained(steps)
    except (OperationNotFoundError, SecurityError, ValueError) as exc:
        return [_error(exc)]


@mcp.tool()
async def search_catalog(
    query: str, limit: int = 10, include_directory: bool = True
) -> list[dict[str, Any]]:
    """Search the built-in catalog of free/public APIs ready to be loaded.

    Covers a curated list (GitHub, Stripe, OpenAI, Wikipedia, weather, ...) plus
    the APIs.guru directory of 2500+ public OpenAPI specs (Google, AWS,
    Microsoft, Twilio, ...). Each result contains a `spec` URL (and sometimes
    `base_url`/`protocol`) to pass straight to `load_api`.

    Args:
        query: Keywords describing the API you need (e.g. "weather forecast").
        limit: Maximum number of results.
        include_directory: Also search the APIs.guru directory (fetched once
            and cached), not just the curated list.
    """
    return await service.search_catalog(query, limit=limit, include_directory=include_directory)


@mcp.tool()
def audit_log(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent outbound calls (method, host, path, status) for auditing."""
    return service.audit_log(limit)


async def _preload(config: Config) -> None:
    """Optionally preload APIs listed in a YAML config file at startup."""
    if not config.apis_config_path:
        return
    from pathlib import Path

    import yaml

    path = Path(config.apis_config_path)
    if not path.exists():
        return
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("apis", []) if isinstance(data, dict) else data
    for entry in entries or []:
        if not isinstance(entry, dict) or "spec" not in entry:
            continue
        try:
            await service.load_api(
                entry["spec"],
                name=entry.get("name"),
                base_url=entry.get("base_url"),
                protocol=entry.get("protocol"),
            )
        except Exception:  # noqa: BLE001  (preload is best-effort)
            continue


def _enable_os_trust_store() -> None:
    """Use the OS certificate store for TLS verification when available.

    This lets the server work behind corporate TLS-inspecting proxies (whose
    root CA lives in the OS store, not certifi) without disabling verification.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:  # noqa: BLE001  (truststore is optional / best-effort)
        pass


async def _startup(config: Config) -> None:
    if config.apis_config_path:
        await _preload(config)
    try:
        # Restore APIs remembered from the previous session (state file).
        await service.restore_state()
    except Exception:  # noqa: BLE001  (never block startup)
        pass


def main() -> None:
    _enable_os_trust_store()
    asyncio.run(_startup(service.config))
    mcp.run()


if __name__ == "__main__":
    main()
