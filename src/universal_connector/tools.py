"""Meta-tool logic, independent of the MCP transport.

`ConnectorService` owns the registry, guard, audit log and auth manager and
exposes the operations that back each MCP tool. Keeping it transport-agnostic
makes the whole flow unit-testable without spinning up a server.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from universal_connector.adapters.base import detect_protocol, get_adapter
from universal_connector.auth.manager import AuthManager
from universal_connector.cache import ResponseCache
from universal_connector.catalog import Catalog
from universal_connector.config import USER_AGENT, Config
from universal_connector.executor.base import get_executor
from universal_connector.models import Protocol
from universal_connector.registry import (
    ApiAlreadyLoadedError,
    ApiNotFoundError,
    OperationNotFoundError,
    Registry,
)
from universal_connector.security.audit import AuditLog
from universal_connector.security.guard import SecurityGuard
from universal_connector.security.net import guarded_send

_REF_PATTERN = re.compile(r"\$\{([^}]+)\}")

# Methods whose results are safe to cache (no side effects).
_CACHEABLE_METHODS = {"GET", "QUERY"}


def _persistable_source(spec: str) -> bool:
    """A spec can be reloaded later only if it is a URL or an existing file."""
    if spec.startswith(("http://", "https://", "grpc://")):
        return True
    try:
        return Path(spec).exists()
    except (OSError, ValueError):
        return False  # raw spec content, not a path


def _lookup_path(context: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path like ``step1.data.items.0.id`` against saved results."""
    cur: Any = context
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _extract_path(data: Any, path: str) -> Any:
    """Pull a value out of ``data`` by dotted path; ``*`` fans out over lists/dicts.

    Examples: ``hourly.temperature_2m``, ``items.0.id``, ``items.*.name``.
    """
    parts = [p for p in path.split(".") if p]

    def walk(cur: Any, idx: int) -> Any:
        if cur is None:
            return None
        if idx == len(parts):
            return cur
        part = parts[idx]
        if part == "*":
            if isinstance(cur, list):
                return [walk(item, idx + 1) for item in cur]
            if isinstance(cur, dict):
                return {k: walk(v, idx + 1) for k, v in cur.items()}
            return None
        if isinstance(cur, list):
            try:
                return walk(cur[int(part)], idx + 1)
            except (ValueError, IndexError):
                return None
        if isinstance(cur, dict):
            return walk(cur.get(part), idx + 1)
        return None

    return walk(data, 0)


def _apply_extract(summary: dict[str, Any], extract: str | list[str] | None) -> dict[str, Any]:
    """Replace the result's data with only the requested paths."""
    if not extract or "data" not in summary:
        return summary
    paths = [extract] if isinstance(extract, str) else list(extract)
    data = summary["data"]
    summary["data"] = {path: _extract_path(data, path) for path in paths}
    summary["extracted"] = True
    return summary


def _resolve_refs(value: Any, context: dict[str, Any]) -> Any:
    """Replace ``${step.path}`` references in step params with prior results."""
    if isinstance(value, str):
        whole = _REF_PATTERN.fullmatch(value.strip())
        if whole:
            return _lookup_path(context, whole.group(1).strip())
        return _REF_PATTERN.sub(
            lambda m: str(_lookup_path(context, m.group(1).strip())), value
        )
    if isinstance(value, dict):
        return {k: _resolve_refs(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, context) for v in value]
    return value


class ConnectorService:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.from_env()
        self.registry = Registry()
        self.guard = SecurityGuard(self.config)
        self.audit = AuditLog(self.config)
        self.auth = AuthManager(self.config)
        self.catalog = Catalog(http_timeout=self.config.http_timeout)
        self.cache = ResponseCache(self.config.cache_ttl)
        # name -> load_api args for APIs whose spec source can be reloaded.
        self._persist: dict[str, dict[str, Any]] = {}
        self._restoring = False

    # --- spec loading --------------------------------------------------

    async def _read_spec(self, source: str) -> str:
        parts = urlsplit(source)
        if parts.scheme in {"http", "https"}:
            # Spec fetching does not enforce the allowlist (you must be able to
            # load specs from arbitrary public hosts), but it MUST still block
            # SSRF to private/internal addresses and re-check every redirect.
            async with httpx.AsyncClient(
                timeout=self.config.http_timeout,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=False,
            ) as client:
                request = client.build_request("GET", source)
                resp = await guarded_send(
                    client, request, self.guard, enforce_allowlist=False
                )
                resp.raise_for_status()
                return resp.text
        candidate = Path(source)
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
        # Fall back to treating the argument as raw spec content.
        return source

    def _derive_name(self, loaded_title: str | None, source: str) -> str:
        if loaded_title:
            slug = "".join(c if c.isalnum() else "_" for c in loaded_title).strip("_")
            if slug:
                return slug.lower()
        host = urlsplit(source).hostname
        if host:
            return host.split(".")[0].lower()
        return "api"

    async def _introspect_graphql(self, endpoint: str) -> str:
        """Run a GraphQL introspection query and return the result as JSON text."""
        from graphql import get_introspection_query

        query = get_introspection_query()
        async with httpx.AsyncClient(
            timeout=self.config.http_timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=False,
        ) as client:
            request = client.build_request("POST", endpoint, json={"query": query})
            resp = await guarded_send(
                client, request, self.guard, enforce_allowlist=False
            )
            resp.raise_for_status()
            return resp.text

    async def load_api(
        self,
        spec: str,
        name: str | None = None,
        base_url: str | None = None,
        protocol: str | None = None,
    ) -> dict[str, Any]:
        content = await self._read_spec(spec)

        if protocol:
            proto = Protocol(protocol.lower())
        else:
            proto = detect_protocol(content, spec)

        # A GraphQL endpoint URL returns no schema on GET; introspect it instead.
        # Only do this when the source is a URL and the body isn't already a
        # schema (SDL passed directly, or a fetched introspection JSON file).
        if proto == Protocol.GRAPHQL:
            source_is_url = spec.startswith(("http://", "https://"))
            looks_like_schema = (
                "__schema" in content
                or "type " in content
                or ("schema" in content and "{" in content)
            )
            if source_is_url and not looks_like_schema:
                content = await self._introspect_graphql(base_url or spec)

        adapter = get_adapter(proto)
        # First pass with a provisional name so we can read the spec title.
        provisional = name or "api"
        loaded, operations = adapter.parse(content, spec, provisional, base_url)

        final_name = name or self._derive_name(loaded.title, spec)
        if final_name != provisional:
            loaded, operations = adapter.parse(content, spec, final_name, base_url)

        if self.registry.has_api(final_name):
            raise ApiAlreadyLoadedError(
                f"API '{final_name}' is already loaded. Unload it first or pass a different name."
            )

        self.registry.add_api(loaded, operations)
        self.guard.register_hosts(loaded.hosts)

        if _persistable_source(spec):
            self._persist[final_name] = {
                "name": final_name,
                "spec": spec,
                "base_url": base_url,
                "protocol": loaded.protocol.value,
            }
            self._save_state()

        auth_setup = self.auth.describe_setup(loaded.auth_schemes, loaded.name)
        result = {
            "name": loaded.name,
            "protocol": loaded.protocol.value,
            "title": loaded.title,
            "version": loaded.version,
            "base_url": loaded.base_url,
            "operation_count": loaded.operation_count,
            "hosts": loaded.hosts,
            "auth_required": [s.type.value for s in loaded.auth_schemes if s.type.value != "none"],
            "auth_setup": auth_setup,
            "hint": "Use search_operations to discover operations, then execute to call them.",
        }
        missing = [s for s in auth_setup if not s["configured"]]
        if missing:
            names = " or ".join(missing[0]["env_vars"][:2])
            result["hint"] = (
                f"Loaded, but no credentials found. To call protected operations, ask the "
                f"user to set {names} in the 'env' block of their MCP config and restart. "
                "Public (unauthenticated) operations may still work."
            )
        return result

    def list_apis(self) -> list[dict[str, Any]]:
        return [
            {
                "name": api.name,
                "protocol": api.protocol.value,
                "title": api.title,
                "base_url": api.base_url,
                "operation_count": api.operation_count,
                "hosts": api.hosts,
            }
            for api in self.registry.list_apis()
        ]

    def unload_api(self, name: str) -> dict[str, Any]:
        api = self.registry.get_api(name)
        hosts = list(api.hosts)
        self.registry.remove_api(name)
        self.guard.unregister_api_hosts(hosts, self.registry.all_hosts())
        self.cache.invalidate_api(name)
        if name in self._persist:
            del self._persist[name]
            self._save_state()
        return {"unloaded": name}

    # --- state persistence ----------------------------------------------

    def _save_state(self) -> None:
        """Remember loaded APIs (spec locations only, never secrets or data)."""
        if not self.config.state_file or self._restoring:
            return
        path = Path(self.config.state_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"version": 1, "apis": list(self._persist.values())}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass  # persistence is best-effort; never break the actual call

    async def restore_state(self) -> list[str]:
        """Reload APIs remembered from a previous session. Best-effort."""
        if not self.config.state_file:
            return []
        path = Path(self.config.state_file)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

        entries = [e for e in data.get("apis", []) if isinstance(e, dict) and e.get("spec")]
        restored: list[str] = []
        self._restoring = True
        try:
            for entry in entries:
                name = entry.get("name")
                # Keep the entry even if this restore attempt fails (e.g. offline),
                # so it isn't silently dropped from the state file later.
                if name:
                    self._persist[name] = entry
                if name and self.registry.has_api(name):
                    continue
                try:
                    await self.load_api(
                        entry["spec"],
                        name=name,
                        base_url=entry.get("base_url"),
                        protocol=entry.get("protocol"),
                    )
                    restored.append(name or entry["spec"])
                except Exception:  # noqa: BLE001
                    continue
        finally:
            self._restoring = False
        return restored

    def search_operations(
        self, query: str, api: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        matches = self.registry.search(query, api=api, limit=limit)
        return [
            {
                "operation_id": op.operation_id,
                "api": op.api_name,
                "method": op.method,
                "path": op.path,
                "summary": op.summary or op.description,
                # Often enough to call execute directly, skipping get_operation.
                "required_params": [p.name for p in op.parameters if p.required],
                "score": round(score, 3),
            }
            for op, score in matches
        ]

    def get_operation(self, operation_id: str) -> dict[str, Any]:
        op = self.registry.get_operation(operation_id)
        return {
            "operation_id": op.operation_id,
            "api": op.api_name,
            "protocol": op.protocol.value,
            "method": op.method,
            "path": op.path,
            "base_url": op.base_url,
            "summary": op.summary,
            "description": op.description,
            "tags": op.tags,
            "input_schema": op.input_schema(),
            "response_schema": op.response_schema,
            "auth_required": [
                {"type": s.type.value, "credential_ref": s.credential_ref}
                for s in op.auth
                if s.type.value != "none"
            ],
        }

    async def execute(
        self,
        operation_id: str,
        params: dict[str, Any] | None = None,
        extract: str | list[str] | None = None,
        fresh: bool = False,
    ) -> dict[str, Any]:
        op = self.registry.get_operation(operation_id)
        params = params or {}

        cacheable = self.cache.enabled and op.method.upper() in _CACHEABLE_METHODS
        cache_key = ResponseCache.key_for(operation_id, params) if cacheable else None
        if cache_key and not fresh:
            hit = self.cache.get(cache_key)
            if hit is not None:
                hit["cached"] = True
                return _apply_extract(hit, extract)

        executor = get_executor(op.protocol)
        # Propagate configured HTTP timeout/retries to the HTTP executor.
        if hasattr(executor, "_timeout"):
            executor._timeout = self.config.http_timeout
        if hasattr(executor, "_max_retries"):
            executor._max_retries = self.config.max_retries
        result = await executor.execute(
            op, params, auth=self.auth, guard=self.guard, audit=self.audit
        )
        summary = result.to_summary()

        if summary.get("ok"):
            if cache_key:
                self.cache.set(cache_key, summary)
            elif self.cache.enabled:
                # A successful mutation may make cached reads for this API stale.
                self.cache.invalidate_api(op.api_name)
        return _apply_extract(summary, extract)

    async def execute_chained(
        self, steps: list[dict[str, Any] | list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """Run a sequence of operations where each step can reference prior results.

        A step is ``{"operation_id", "params"?, "save_as"?, "extract"?, "fresh"?,
        "stop_on_error"?}``. Params may contain ``${save_as.path.to.value}``
        references resolved from earlier step results.

        A list of steps in place of a single step is a **parallel group**: its
        steps run concurrently (they may only reference results from earlier in
        the chain, not each other) and later steps can reference each of them.
        """
        context: dict[str, Any] = {}
        results: list[dict[str, Any]] = []
        counter = 0
        for item in steps or []:
            group = item if isinstance(item, list) else [item]
            if any(not isinstance(step, dict) or not step.get("operation_id") for step in group):
                results.append({"error": "step missing 'operation_id'"})
                break

            prepared: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
            for step in group:
                counter += 1
                save_as = step.get("save_as") or f"step{counter}"
                params = _resolve_refs(step.get("params", {}) or {}, context)
                prepared.append((step, save_as, params))

            outcomes = await asyncio.gather(
                *(
                    self.execute(
                        step["operation_id"],
                        params,
                        extract=step.get("extract"),
                        fresh=bool(step.get("fresh")),
                    )
                    for step, _, params in prepared
                )
            )

            stop = False
            for (step, save_as, _), result in zip(prepared, outcomes, strict=True):
                context[save_as] = result
                results.append(
                    {"step": save_as, "operation_id": step["operation_id"], "result": result}
                )
                if not result.get("ok", False) and step.get("stop_on_error", True):
                    stop = True
            if stop:
                break
        return results

    async def search_catalog(
        self, query: str, limit: int = 10, include_directory: bool = True
    ) -> list[dict[str, Any]]:
        results = await self.catalog.search(query, limit=limit, include_directory=include_directory)
        for result in results:
            result["hint"] = (
                "Pass 'spec' (plus 'name', 'base_url' and 'protocol' when present) to load_api."
            )
        return results

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.audit.recent(limit)


# Exceptions re-exported so the server can turn them into friendly messages.
__all__ = [
    "ConnectorService",
    "ApiAlreadyLoadedError",
    "ApiNotFoundError",
    "OperationNotFoundError",
]
