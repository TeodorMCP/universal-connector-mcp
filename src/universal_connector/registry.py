"""In-memory registry of loaded APIs and their operations.

Provides fuzzy search so an agent can discover operations without every
endpoint being registered as an individual MCP tool (which would overflow the
context window on large APIs).
"""

from __future__ import annotations

from difflib import SequenceMatcher
from urllib.parse import urlsplit

from universal_connector.models import LoadedApi, Operation


class ApiAlreadyLoadedError(Exception):
    pass


class ApiNotFoundError(Exception):
    pass


class OperationNotFoundError(Exception):
    pass


def _host_of(url: str) -> str | None:
    try:
        host = urlsplit(url).hostname
        return host.lower() if host else None
    except ValueError:
        return None


class Registry:
    """Holds loaded APIs and offers lookup / search over their operations."""

    def __init__(self) -> None:
        self._apis: dict[str, LoadedApi] = {}
        # operation_id -> Operation. operation_id is namespaced as "<api>.<op>".
        self._operations: dict[str, Operation] = {}

    # --- API lifecycle -------------------------------------------------

    def add_api(self, api: LoadedApi, operations: list[Operation]) -> None:
        if api.name in self._apis:
            raise ApiAlreadyLoadedError(
                f"API '{api.name}' is already loaded. Unload it first to reload."
            )
        hosts = set(api.hosts)
        for op in operations:
            self._operations[op.operation_id] = op
            host = _host_of(op.base_url)
            if host:
                hosts.add(host)
        api.hosts = sorted(hosts)
        api.operation_count = len(operations)
        self._apis[api.name] = api

    def remove_api(self, name: str) -> None:
        if name not in self._apis:
            raise ApiNotFoundError(f"API '{name}' is not loaded.")
        del self._apis[name]
        self._operations = {
            op_id: op for op_id, op in self._operations.items() if op.api_name != name
        }

    def has_api(self, name: str) -> bool:
        return name in self._apis

    def get_api(self, name: str) -> LoadedApi:
        if name not in self._apis:
            raise ApiNotFoundError(f"API '{name}' is not loaded.")
        return self._apis[name]

    def list_apis(self) -> list[LoadedApi]:
        return list(self._apis.values())

    def all_hosts(self) -> set[str]:
        hosts: set[str] = set()
        for api in self._apis.values():
            hosts.update(api.hosts)
        return hosts

    # --- Operation lookup ---------------------------------------------

    def get_operation(self, operation_id: str) -> Operation:
        op = self._operations.get(operation_id)
        if op is None:
            raise OperationNotFoundError(
                f"Operation '{operation_id}' not found. Use search_operations to discover valid ids."
            )
        return op

    def search(
        self, query: str, api: str | None = None, limit: int = 20
    ) -> list[tuple[Operation, float]]:
        """Return operations ranked by relevance to ``query``.

        Scoring combines substring hits (strong signal) with a fuzzy ratio so
        both exact keywords and approximate matches surface.
        """
        query_l = query.strip().lower()
        candidates = [
            op
            for op in self._operations.values()
            if api is None or op.api_name == api
        ]
        if not query_l:
            return [(op, 0.0) for op in candidates[:limit]]

        scored: list[tuple[Operation, float]] = []
        terms = [t for t in query_l.split() if t]
        for op in candidates:
            text = op.search_text()
            score = 0.0
            for term in terms:
                if term in text:
                    score += 1.0
                if term in op.operation_id.lower():
                    score += 1.0  # id matches are especially meaningful
            score += SequenceMatcher(None, query_l, op.search_text()).ratio()
            if score > 0:
                scored.append((op, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]
