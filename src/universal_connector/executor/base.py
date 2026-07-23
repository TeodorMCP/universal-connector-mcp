"""Executor interface and shared result type.

Executors take a normalized `Operation` plus a params dict and perform the
actual call for their protocol. Auth injection, host allow-listing, response
capping and audit logging are supplied by the caller so every protocol behaves
consistently.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from universal_connector.models import Operation, Protocol

if TYPE_CHECKING:
    from universal_connector.auth.manager import AuthManager
    from universal_connector.security.audit import AuditLog
    from universal_connector.security.guard import SecurityGuard


@dataclass
class ExecutionResult:
    """Normalized outcome of an operation call."""

    ok: bool
    status: int | None = None
    data: Any = None
    raw_text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    truncated: bool = False
    error: str | None = None

    def to_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {"ok": self.ok, "status": self.status}
        if self.error:
            summary["error"] = self.error
        if self.data is not None:
            summary["data"] = self.data
        elif self.raw_text:
            summary["data"] = self.raw_text
        if self.truncated:
            summary["truncated"] = True
            summary["note"] = (
                "Response truncated to fit the context window limit. "
                "Pass extract=[\"path.to.field\"] to receive only the fields you need."
            )
        return summary


class Executor(ABC):
    """Base class for protocol executors."""

    protocol: Protocol

    @abstractmethod
    async def execute(
        self,
        operation: Operation,
        params: dict[str, Any],
        *,
        auth: AuthManager,
        guard: SecurityGuard,
        audit: AuditLog,
    ) -> ExecutionResult:
        raise NotImplementedError


def get_executor(protocol: Protocol) -> Executor:
    """Return an executor instance for ``protocol`` (lazy imports)."""
    if protocol == Protocol.OPENAPI:
        from universal_connector.executor.http import HttpExecutor

        return HttpExecutor()
    if protocol == Protocol.GRAPHQL:
        from universal_connector.executor.graphql import GraphQLExecutor

        return GraphQLExecutor()
    if protocol == Protocol.GRPC:
        from universal_connector.executor.grpc import GrpcExecutor

        return GrpcExecutor()
    if protocol == Protocol.SOAP:
        from universal_connector.executor.soap import SoapExecutor

        return SoapExecutor()
    raise ValueError(f"No executor for protocol '{protocol}'.")
