"""GraphQL executor.

Builds a query/mutation string from the normalized operation plus the caller's
params, supports GraphQL-style field selection (the caller may pass a ``fields``
selection set to trim the response), and applies the same guard/auth/audit flow
as the HTTP executor.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from universal_connector.auth.manager import AuthManager
from universal_connector.config import USER_AGENT
from universal_connector.executor.base import ExecutionResult, Executor
from universal_connector.models import Operation, Protocol
from universal_connector.security.audit import AuditEntry, AuditLog
from universal_connector.security.guard import SecurityError, SecurityGuard
from universal_connector.security.net import guarded_send


class GraphQLExecutor(Executor):
    protocol = Protocol.GRAPHQL

    def __init__(self, timeout: float = 30.0, max_retries: int = 1) -> None:
        self._timeout = timeout
        self._max_retries = max_retries

    async def execute(
        self,
        operation: Operation,
        params: dict[str, Any],
        *,
        auth: AuthManager,
        guard: SecurityGuard,
        audit: AuditLog,
    ) -> ExecutionResult:
        params = dict(params or {})
        selection_override = params.pop("fields", None)

        query_str = self._build_query(operation, params, selection_override)
        variables = {k: v for k, v in params.items() if k != "fields"}

        url = operation.base_url
        host = urlsplit(url).hostname or ""
        try:
            guard.check_url(url)
        except SecurityError as exc:
            audit.record(self._entry(operation, host, None, False, str(exc)))
            return ExecutionResult(ok=False, error=str(exc))

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        await auth.prepare(operation, guard)
        artifacts = auth.build_http_auth(operation, guard)
        headers.update(artifacts.headers)

        payload = {"query": query_str, "variables": variables}

        result = await self._send(url, payload, headers, guard)
        audit.record(self._entry(operation, host, result.status, result.ok, result.error))
        return result

    def _build_query(
        self, operation: Operation, params: dict[str, Any], selection_override: Any
    ) -> str:
        op_type = operation.extra.get("operation_type", "query")
        field_name = operation.extra.get("field_name", operation.path)
        arg_types: dict[str, str] = operation.extra.get("arg_types", {})

        provided = [name for name in params if name in arg_types]
        var_decls = ", ".join(f"${name}: {arg_types[name]}" for name in provided)
        call_args = ", ".join(f"{name}: ${name}" for name in provided)

        if selection_override:
            selection = str(selection_override).strip()
            if selection and not selection.startswith("{"):
                selection = "{ " + selection + " }"
        else:
            selection = operation.extra.get("default_selection", "")

        header = f"{op_type}"
        if var_decls:
            header += f" ({var_decls})"
        call = field_name
        if call_args:
            call += f"({call_args})"
        return f"{header} {{ {call} {selection} }}".strip()

    async def _send(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        guard: SecurityGuard,
    ) -> ExecutionResult:
        attempt = 0
        last_error: str | None = None
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            while attempt <= self._max_retries:
                attempt += 1
                try:
                    request = client.build_request("POST", url, json=payload, headers=headers)
                    response = await guarded_send(
                        client, request, guard, enforce_allowlist=True
                    )
                except SecurityError as exc:
                    return ExecutionResult(ok=False, error=str(exc))
                except httpx.HTTPError as exc:
                    last_error = guard.redact(f"HTTP error: {exc}")
                    continue
                raw_text = response.text or ""
                capped, truncated = guard.cap_response(raw_text)
                capped = guard.redact(capped)
                data: Any = None
                errors: Any = None
                if not truncated:
                    try:
                        parsed = json.loads(raw_text)
                        data = parsed.get("data")
                        errors = parsed.get("errors")
                    except (json.JSONDecodeError, ValueError):
                        data = None
                ok = response.is_success and not errors
                return ExecutionResult(
                    ok=ok,
                    status=response.status_code,
                    data={"data": data, "errors": errors} if data is not None or errors else None,
                    raw_text="" if data is not None or errors else capped,
                    truncated=truncated,
                    error=None if ok else (guard.redact(json.dumps(errors)) if errors else f"HTTP {response.status_code}"),
                )
        return ExecutionResult(ok=False, error=last_error or "Request failed.")

    def _entry(
        self,
        operation: Operation,
        host: str,
        status: int | None,
        ok: bool,
        error: str | None,
    ) -> AuditEntry:
        return AuditEntry(
            timestamp=time.time(),
            api_name=operation.api_name,
            operation_id=operation.operation_id,
            protocol=operation.protocol.value,
            method=operation.method,
            host=host,
            path=operation.path,
            status=status,
            ok=ok,
            error=error,
        )
