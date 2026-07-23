"""Audit logging of outbound calls.

Records enough to answer "what did the agent call and when" without ever
persisting secrets or full request/response bodies. Entries are kept in memory
and optionally appended to a file.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from universal_connector.config import Config


@dataclass
class AuditEntry:
    timestamp: float
    api_name: str
    operation_id: str
    protocol: str
    method: str
    host: str
    path: str
    status: int | None
    ok: bool
    error: str | None = None

    def iso_time(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp))


class AuditLog:
    def __init__(self, config: Config, max_entries: int = 500) -> None:
        self._enabled = config.audit_enabled
        self._file = Path(config.audit_file) if config.audit_file else None
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)

    def record(self, entry: AuditEntry) -> None:
        if not self._enabled:
            return
        self._entries.append(entry)
        if self._file is not None:
            try:
                line = json.dumps({**asdict(entry), "time": entry.iso_time()})
                with self._file.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                # Never let audit persistence break a real call.
                pass

    def recent(self, limit: int = 50) -> list[dict]:
        items = list(self._entries)[-limit:]
        return [{**asdict(e), "time": e.iso_time()} for e in items]
