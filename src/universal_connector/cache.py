"""In-memory TTL cache for read-only operation results.

Only successful, side-effect-free calls (HTTP GET, GraphQL queries) are cached,
keyed by operation id plus canonicalized params. Any successful mutating call
invalidates the cache for its API so agents don't read stale data they just
changed themselves.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any


class ResponseCache:
    def __init__(self, ttl_seconds: float = 0.0) -> None:
        self.ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    @staticmethod
    def key_for(operation_id: str, params: dict[str, Any]) -> str:
        canonical = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
        # operation_id is namespaced as "<api>.<op>", so the api prefix survives
        # in the key and per-API invalidation stays a simple prefix match.
        return f"{operation_id}|{digest}"

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if time.monotonic() - stored_at >= self.ttl:
            del self._store[key]
            return None
        return copy.deepcopy(value)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = (time.monotonic(), copy.deepcopy(value))

    def invalidate_api(self, api_name: str) -> None:
        prefix = f"{api_name}."
        for key in [k for k in self._store if k.startswith(prefix)]:
            del self._store[key]

    def clear(self) -> None:
        self._store.clear()
