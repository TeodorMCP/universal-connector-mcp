"""Outbound request guard and secret redaction.

The guard is the core of the "security-first" promise: every outbound call must
pass ``check_url`` before it happens. By default only hosts belonging to loaded
specs are reachable, which blocks an operation (or a manipulated spec) from
exfiltrating data to an arbitrary domain.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from universal_connector.config import Config


class SecurityError(Exception):
    """Raised when a request violates the security policy."""


class SecurityGuard:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._allowed: set[str] = {h.lower() for h in config.allowed_hosts}
        self._denied: set[str] = {h.lower() for h in config.denied_hosts}
        # Hosts registered dynamically as APIs are loaded.
        self._registered: set[str] = set()
        self._secrets: set[str] = set()

    # --- host policy ---------------------------------------------------

    def register_hosts(self, hosts: list[str]) -> None:
        for host in hosts:
            if host:
                self._registered.add(host.lower())

    def unregister_api_hosts(self, hosts: list[str], still_used: set[str]) -> None:
        """Drop hosts no longer referenced by any loaded API."""
        for host in hosts:
            h = host.lower()
            if h not in still_used:
                self._registered.discard(h)

    def _host_denied(self, host: str) -> bool:
        if host in self._denied:
            return True
        # Denylist can use suffix matches like ".internal".
        return any(d.startswith(".") and host.endswith(d) for d in self._denied)

    def _host_allowed(self, host: str) -> bool:
        host = host.lower()
        if self._host_denied(host):
            return False
        if self._config.allow_all_hosts:
            return True
        if host in self._allowed or host in self._registered:
            return True
        for allowed in self._allowed:
            if allowed.startswith(".") and host.endswith(allowed):
                return True
        return False

    def host_explicitly_allowed(self, host: str) -> bool:
        """True only if the user named this host in ``UCMCP_ALLOWED_HOSTS``.

        This gates the private-IP (SSRF) bypass. Note that ``allow_all_hosts``
        deliberately does NOT count here: disabling the allowlist must not also
        silently open the internal network / cloud-metadata endpoint. Reaching
        an internal address requires either a specific allowlist entry or
        ``UCMCP_BLOCK_PRIVATE_IPS=false``. Spec-derived (registered) hosts also
        do not count - loading a spec must not grant internal access.
        """
        host = host.lower()
        if host in self._allowed:
            return True
        return any(a.startswith(".") and host.endswith(a) for a in self._allowed)

    @property
    def block_private_ips(self) -> bool:
        return self._config.block_private_ips

    @property
    def max_redirects(self) -> int:
        return self._config.max_redirects

    def check_scheme(self, url: str) -> str:
        """Validate the URL scheme and return the host. Used for spec fetches."""
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https", "grpc", "grpcs"}:
            raise SecurityError(f"Blocked non-web scheme: {parts.scheme!r}")
        host = parts.hostname
        if not host:
            raise SecurityError(f"Could not determine host for URL: {url!r}")
        if self._host_denied(host.lower()):
            raise SecurityError(f"Host '{host}' is explicitly denied.")
        return host

    def check_url(self, url: str) -> None:
        host = self.check_scheme(url)
        if not self._host_allowed(host):
            raise SecurityError(
                f"Host '{host}' is not allowed. Add it to UCMCP_ALLOWED_HOSTS "
                f"or load an API served from that host."
            )

    # --- secret redaction ---------------------------------------------

    def register_secret(self, secret: str | None) -> None:
        if secret and len(secret) >= 4:
            self._secrets.add(secret)

    def redact(self, text: str) -> str:
        if not text:
            return text
        redacted = text
        for secret in self._secrets:
            redacted = redacted.replace(secret, "***REDACTED***")
        # Best-effort masking of common token patterns even if not registered.
        redacted = re.sub(
            r"(?i)(authorization\"?\s*[:=]\s*\"?)(bearer\s+)?[A-Za-z0-9._\-]{12,}",
            r"\1***REDACTED***",
            redacted,
        )
        return redacted

    # --- response capping ---------------------------------------------

    def cap_response(self, text: str) -> tuple[str, bool]:
        limit = self._config.max_response_bytes
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= limit:
            return text, False
        truncated = encoded[:limit].decode("utf-8", errors="ignore")
        return truncated, True
