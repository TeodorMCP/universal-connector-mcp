"""HTTP executor for OpenAPI/REST operations.

Builds the request from the normalized `Operation` and the caller's params,
enforces the security guard before the call, applies auth, retries on transient
failures, caps the response size, and records an audit entry.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from universal_connector.auth.manager import AuthManager
from universal_connector.config import USER_AGENT
from universal_connector.executor.base import ExecutionResult, Executor
from universal_connector.models import Operation, ParameterLocation, Protocol
from universal_connector.security.audit import AuditEntry, AuditLog
from universal_connector.security.guard import SecurityError, SecurityGuard

_RETRY_STATUS = {429, 502, 503, 504}


class HttpExecutor(Executor):
    protocol = Protocol.OPENAPI

    def __init__(self, timeout: float = 30.0, max_retries: int = 2) -> None:
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
        params = params or {}
        path = operation.path
        query: dict[str, Any] = {}
        headers: dict[str, str] = {"Accept": "application/json", "User-Agent": USER_AGENT}
        cookies: dict[str, str] = {}
        body: Any = params.get("body")

        for param in operation.parameters:
            if param.name not in params:
                continue
            value = params[param.name]
            if param.location == ParameterLocation.PATH:
                path = path.replace(f"{{{param.name}}}", str(value))
            elif param.location == ParameterLocation.QUERY:
                query[param.name] = value
            elif param.location == ParameterLocation.HEADER:
                headers[param.name] = str(value)
            elif param.location == ParameterLocation.COOKIE:
                cookies[param.name] = str(value)

        url = operation.base_url.rstrip("/") + "/" + path.lstrip("/")

        await auth.prepare(operation, guard)
        artifacts = auth.build_http_auth(operation, guard)
        headers.update(artifacts.headers)
        query.update(artifacts.query)

        host = urlsplit(url).hostname or ""
        try:
            guard.check_url(url)
        except SecurityError as exc:
            audit.record(self._entry(operation, host, path, None, False, str(exc)))
            return ExecutionResult(ok=False, error=str(exc))

        result = await self._send(
            operation=operation,
            url=url,
            query=query,
            headers=headers,
            cookies=cookies,
            body=body,
            guard=guard,
        )
        audit.record(
            self._entry(operation, host, path, result.status, result.ok, result.error)
        )
        return result

    async def _send(
        self,
        *,
        operation: Operation,
        url: str,
        query: dict[str, Any],
        headers: dict[str, str],
        cookies: dict[str, str],
        body: Any,
        guard: SecurityGuard,
    ) -> ExecutionResult:
        json_body = None
        content = None
        if body is not None:
            if isinstance(body, (dict, list)):
                json_body = body
            else:
                content = str(body)

        attempt = 0
        last_error: str | None = None
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            while attempt <= self._max_retries:
                attempt += 1
                try:
                    response = await client.request(
                        operation.method,
                        url,
                        params=query or None,
                        headers=headers,
                        cookies=cookies or None,
                        json=json_body,
                        content=content,
                    )
                except httpx.TimeoutException:
                    last_error = "Request timed out."
                except httpx.HTTPError as exc:
                    last_error = guard.redact(f"HTTP error: {exc}")
                else:
                    if response.status_code in _RETRY_STATUS and attempt <= self._max_retries:
                        await asyncio.sleep(min(2 ** (attempt - 1), 5))
                        continue
                    return self._to_result(response, guard)

                if attempt <= self._max_retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 5))

        return ExecutionResult(ok=False, error=last_error or "Request failed.")

    def _to_result(self, response: httpx.Response, guard: SecurityGuard) -> ExecutionResult:
        raw_text = response.text or ""
        capped, truncated = guard.cap_response(raw_text)
        capped = guard.redact(capped)

        data: Any = None
        ctype = response.headers.get("content-type", "")
        if "json" in ctype and not truncated:
            try:
                data = json.loads(raw_text)
            except (json.JSONDecodeError, ValueError):
                data = None

        safe_headers = {
            k: v
            for k, v in response.headers.items()
            if k.lower() not in {"set-cookie", "authorization"}
        }
        return ExecutionResult(
            ok=response.is_success,
            status=response.status_code,
            data=data,
            raw_text="" if data is not None else capped,
            headers=safe_headers,
            truncated=truncated,
            error=None if response.is_success else f"HTTP {response.status_code}",
        )

    def _entry(
        self,
        operation: Operation,
        host: str,
        path: str,
        status: int | None,
        ok: bool,
        error: str | None,
    ) -> AuditEntry:
        import time

        return AuditEntry(
            timestamp=time.time(),
            api_name=operation.api_name,
            operation_id=operation.operation_id,
            protocol=operation.protocol.value,
            method=operation.method,
            host=host,
            path=path,
            status=status,
            ok=ok,
            error=error,
        )
