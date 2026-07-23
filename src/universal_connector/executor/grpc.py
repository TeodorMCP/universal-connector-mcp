"""gRPC executor (via reflection + dynamic messages).

Rebuilds the request/response message types from server reflection, converts the
caller's JSON params into a protobuf message, performs a unary-unary call and
serializes the response back to a dict. Bearer tokens (if configured) are sent
as ``authorization`` metadata.
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


class GrpcExecutor(Executor):
    protocol = Protocol.GRPC

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

        metadata: list[tuple[str, str]] = []
        artifacts = auth.build_http_auth(operation, guard)
        if "Authorization" in artifacts.headers:
            metadata.append(("authorization", artifacts.headers["Authorization"]))

        try:
            result = await asyncio.to_thread(self._call, operation, body, metadata, guard)
        except Exception as exc:  # noqa: BLE001
            msg = guard.redact(f"gRPC call failed: {exc}")
            audit.record(self._entry(operation, host, False, msg))
            return ExecutionResult(ok=False, error=msg)

        audit.record(self._entry(operation, host, result.ok, result.error))
        return result

    def _call(
        self,
        operation: Operation,
        body: dict[str, Any],
        metadata: list[tuple[str, str]],
        guard: SecurityGuard,
    ) -> ExecutionResult:
        import grpc
        from google.protobuf import json_format
        from google.protobuf.descriptor_pool import DescriptorPool
        from google.protobuf.message_factory import GetMessageClass
        from grpc_reflection.v1alpha.proto_reflection_descriptor_database import (
            ProtoReflectionDescriptorDatabase,
        )

        scheme = urlsplit(operation.base_url).scheme
        target = operation.extra["target"]
        if scheme == "grpcs":
            channel = grpc.secure_channel(target, grpc.ssl_channel_credentials())
        else:
            channel = grpc.insecure_channel(target)

        try:
            db = ProtoReflectionDescriptorDatabase(channel)
            pool = DescriptorPool(db)
            req_desc = pool.FindMessageTypeByName(operation.extra["input_type"])
            resp_desc = pool.FindMessageTypeByName(operation.extra["output_type"])
            req_cls = GetMessageClass(req_desc)
            resp_cls = GetMessageClass(resp_desc)

            request = req_cls()
            json_format.ParseDict(body, request)

            rpc = channel.unary_unary(
                operation.extra["full_method"],
                request_serializer=req_cls.SerializeToString,
                response_deserializer=resp_cls.FromString,
            )
            response = rpc(request, timeout=self._timeout, metadata=metadata or None)
            data = json_format.MessageToDict(response)
            text, truncated = guard.cap_response(str(data))
            return ExecutionResult(
                ok=True,
                status=0,
                data=None if truncated else data,
                raw_text=guard.redact(text) if truncated else "",
                truncated=truncated,
            )
        finally:
            channel.close()

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
            status=0 if ok else None,
            ok=ok,
            error=error,
        )
