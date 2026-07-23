"""SOAP executor (via zeep).

zeep is synchronous, so the call runs in a worker thread. The operation is
invoked through a bound service proxy and the response object is serialized to a
plain dict for the agent.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlsplit

from universal_connector.auth.manager import AuthManager
from universal_connector.executor.base import ExecutionResult, Executor
from universal_connector.models import Operation, Protocol
from universal_connector.security.audit import AuditEntry, AuditLog
from universal_connector.security.guard import SecurityError, SecurityGuard


class SoapExecutor(Executor):
    protocol = Protocol.SOAP

    def __init__(self, timeout: float = 30.0, max_retries: int = 0) -> None:
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
        url = operation.base_url
        host = urlsplit(url).hostname or ""
        try:
            guard.check_url(url)
        except SecurityError as exc:
            audit.record(self._entry(operation, host, False, str(exc)))
            return ExecutionResult(ok=False, error=str(exc))

        body = (params or {}).get("body", {})
        if not isinstance(body, dict):
            body = {}

        try:
            result = await asyncio.to_thread(self._call, operation, body, guard)
        except Exception as exc:  # noqa: BLE001
            msg = guard.redact(f"SOAP call failed: {exc}")
            audit.record(self._entry(operation, host, False, msg))
            return ExecutionResult(ok=False, error=msg)

        audit.record(self._entry(operation, host, True, None))
        return result

    def _call(self, operation: Operation, body: dict[str, Any], guard: SecurityGuard) -> ExecutionResult:
        from zeep import Client
        from zeep.helpers import serialize_object

        client = Client(operation.extra["wsdl"])
        service_proxy = client.bind(operation.extra["service"], operation.extra["port"])
        op_name = operation.extra["operation"]
        method = getattr(service_proxy, op_name)
        raw = method(**body)
        data = serialize_object(raw)
        text, truncated = guard.cap_response(str(data))
        return ExecutionResult(
            ok=True,
            status=200,
            data=None if truncated else data,
            raw_text=guard.redact(text) if truncated else "",
            truncated=truncated,
        )

    def _entry(
        self, operation: Operation, host: str, ok: bool, error: str | None
    ) -> AuditEntry:
        return AuditEntry(
            timestamp=time.time(),
            api_name=operation.api_name,
            operation_id=operation.operation_id,
            protocol=operation.protocol.value,
            method=operation.method,
            host=host,
            path=operation.path,
            status=200 if ok else None,
            ok=ok,
            error=error,
        )
