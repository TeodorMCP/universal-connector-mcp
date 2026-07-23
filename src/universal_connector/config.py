"""Runtime configuration loaded from environment variables.

All settings are namespaced with the ``UCMCP_`` prefix so they are easy to set
from an MCP client config (``env`` block) without colliding with anything else.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_PREFIX = "UCMCP_"

# Sent on all outbound requests. Some APIs (e.g. Wikimedia) reject the default
# python-httpx user agent outright.
USER_AGENT = "universal-connector-mcp/0.1 (+https://github.com/universal-connector-mcp)"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(ENV_PREFIX + name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_list(name: str) -> list[str]:
    raw = _env(name)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    """Central configuration for the server."""

    # Security guard
    allowed_hosts: list[str] = field(default_factory=list)
    denied_hosts: list[str] = field(default_factory=list)
    allow_all_hosts: bool = False
    max_response_bytes: int = 100_000

    # HTTP executor
    http_timeout: float = 30.0
    max_retries: int = 2

    # TTL (seconds) for caching successful read-only responses. 0 disables.
    cache_ttl: float = 60.0

    # Auditing
    audit_enabled: bool = True
    audit_file: str | None = None

    # Credentials
    use_keyring: bool = False

    # Optional preload of APIs from a YAML config file
    apis_config_path: str | None = None

    # Where to remember loaded APIs between restarts (None disables).
    # Only spec locations are stored - never credentials or response data.
    state_file: str | None = None

    @classmethod
    def from_env(cls) -> Config:
        raw_state = _env("STATE_FILE")
        if raw_state is None:
            state_file: str | None = str(
                Path.home() / ".universal-connector-mcp" / "state.json"
            )
        elif raw_state.strip() == "" or raw_state.strip().lower() in {"0", "off", "false", "none"}:
            state_file = None
        else:
            state_file = raw_state
        return cls(
            allowed_hosts=_env_list("ALLOWED_HOSTS"),
            denied_hosts=_env_list("DENIED_HOSTS"),
            allow_all_hosts=_env_bool("ALLOW_ALL_HOSTS", False),
            max_response_bytes=_env_int("MAX_RESPONSE_BYTES", 100_000),
            http_timeout=float(_env_int("HTTP_TIMEOUT", 30)),
            max_retries=_env_int("MAX_RETRIES", 2),
            cache_ttl=float(_env_int("CACHE_TTL", 60)),
            audit_enabled=_env_bool("AUDIT_ENABLED", True),
            audit_file=_env("AUDIT_FILE"),
            use_keyring=_env_bool("USE_KEYRING", False),
            apis_config_path=_env("APIS_CONFIG"),
            state_file=state_file,
        )
