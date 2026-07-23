"""Credential resolution and injection.

Secrets are read from environment variables (and optionally the OS keyring) at
request time only. They are never stored on the models and are registered with
the `SecurityGuard` so they get redacted from audit logs and errors.
"""

from __future__ import annotations

import base64
import os
import re
import time
from typing import TYPE_CHECKING

import httpx

from universal_connector.config import Config
from universal_connector.models import AuthScheme, AuthType, Operation, ParameterLocation

if TYPE_CHECKING:
    from universal_connector.security.guard import SecurityGuard


class HttpAuthArtifacts:
    """Concrete auth material to apply to an HTTP request."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.query: dict[str, str] = {}
        self.basic: tuple[str, str] | None = None


class AuthManager:
    def __init__(self, config: Config) -> None:
        self._config = config
        # Cache of OAuth2 access tokens: key -> (token, expires_at_epoch).
        self._token_cache: dict[str, tuple[str, float]] = {}

    # --- secret resolution --------------------------------------------

    def _from_keyring(self, name: str) -> str | None:
        if not self._config.use_keyring:
            return None
        try:
            import keyring

            return keyring.get_password("universal-connector-mcp", name)
        except Exception:  # noqa: BLE001
            return None

    def _lookup(self, name: str) -> str | None:
        value = os.environ.get(name)
        if value:
            return value
        return self._from_keyring(name)

    def _base_prefix(self, api_name: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "_", api_name).upper().strip("_")

    def _candidates(self, scheme: AuthScheme, api_name: str) -> list[str]:
        base = self._base_prefix(api_name)
        cands: list[str] = []
        if scheme.credential_ref:
            cands.append(scheme.credential_ref)
        for suffix in ("TOKEN", "API_KEY", "APIKEY", "KEY", "SECRET", "PAT"):
            cands.append(f"{base}_{suffix}")
        # De-duplicate while preserving order.
        seen: set[str] = set()
        return [c for c in cands if not (c in seen or seen.add(c))]

    def resolve_secret(self, scheme: AuthScheme, api_name: str) -> str | None:
        for name in self._candidates(scheme, api_name):
            value = self._lookup(name)
            if value:
                return value
        return None

    def describe_setup(self, schemes: list[AuthScheme], api_name: str) -> list[dict]:
        """Explain, per auth scheme, whether credentials are configured and
        which environment variables the server will look for.

        Used to give users an exact, copy-pasteable setup hint instead of
        making them guess variable names. Never returns secret values.
        """
        base = self._base_prefix(api_name)
        described: list[dict] = []
        seen_types: set[str] = set()
        for scheme in schemes:
            if scheme.type == AuthType.NONE or scheme.type.value in seen_types:
                continue
            seen_types.add(scheme.type.value)
            if scheme.type == AuthType.OAUTH2:
                env_vars = [f"{base}_CLIENT_ID", f"{base}_CLIENT_SECRET"]
                configured = bool(
                    self._lookup(env_vars[0]) and self._lookup(env_vars[1])
                ) or self.resolve_secret(scheme, api_name) is not None
            elif scheme.type == AuthType.BASIC:
                env_vars = [f"{base}_USERNAME", f"{base}_PASSWORD"]
                configured = self._resolve_basic(scheme, api_name) is not None
            else:
                env_vars = self._candidates(scheme, api_name)[:3]
                configured = self.resolve_secret(scheme, api_name) is not None
            described.append(
                {
                    "type": scheme.type.value,
                    "configured": configured,
                    "env_vars": env_vars,
                }
            )
        return described

    def _resolve_basic(self, scheme: AuthScheme, api_name: str) -> tuple[str, str] | None:
        base = self._base_prefix(api_name)
        raw = self.resolve_secret(scheme, api_name)
        if raw and ":" in raw:
            user, _, password = raw.partition(":")
            return user, password
        user = self._lookup(f"{base}_USERNAME") or self._lookup(f"{base}_USER")
        password = self._lookup(f"{base}_PASSWORD") or self._lookup(f"{base}_PASS")
        if user is not None and password is not None:
            return user, password
        return None

    # --- OAuth2 (client credentials) ----------------------------------

    async def prepare(
        self, operation: Operation, guard: SecurityGuard | None = None
    ) -> None:
        """Acquire and cache OAuth2 tokens the operation needs, if configured."""
        for scheme in operation.auth:
            if scheme.type == AuthType.OAUTH2:
                await self._ensure_oauth_token(scheme, operation.api_name, guard)

    def _cache_key(self, scheme: AuthScheme, api_name: str) -> str:
        return f"{api_name}:{scheme.credential_ref or 'oauth2'}"

    async def _ensure_oauth_token(
        self, scheme: AuthScheme, api_name: str, guard: SecurityGuard | None
    ) -> str | None:
        key = self._cache_key(scheme, api_name)
        cached = self._token_cache.get(key)
        if cached and cached[1] > time.time() + 30:
            return cached[0]

        base = self._base_prefix(api_name)
        client_id = self._lookup(f"{base}_CLIENT_ID")
        client_secret = self._lookup(f"{base}_CLIENT_SECRET")
        token_url = scheme.token_url or self._lookup(f"{base}_TOKEN_URL")
        if not (client_id and client_secret and token_url):
            return None

        if guard is not None:
            from urllib.parse import urlsplit

            host = urlsplit(token_url).hostname
            if host:
                guard.register_hosts([host])
                guard.check_url(token_url)

        data = {"grant_type": "client_credentials"}
        if scheme.scopes:
            data["scope"] = " ".join(scheme.scopes)
        try:
            async with httpx.AsyncClient(timeout=self._config.http_timeout) as client:
                resp = await client.post(token_url, data=data, auth=(client_id, client_secret))
                resp.raise_for_status()
                payload = resp.json()
        except (httpx.HTTPError, ValueError):
            return None

        token = payload.get("access_token")
        if not token:
            return None
        expires_in = payload.get("expires_in", 3600)
        try:
            expires_at = time.time() + float(expires_in)
        except (TypeError, ValueError):
            expires_at = time.time() + 3600
        self._token_cache[key] = (token, expires_at)
        if guard is not None:
            guard.register_secret(token)
        return token

    # --- application ---------------------------------------------------

    def build_http_auth(
        self, operation: Operation, guard: SecurityGuard | None = None
    ) -> HttpAuthArtifacts:
        artifacts = HttpAuthArtifacts()
        for scheme in operation.auth:
            if scheme.type == AuthType.NONE:
                continue
            if scheme.type == AuthType.API_KEY:
                secret = self.resolve_secret(scheme, operation.api_name)
                if not secret:
                    continue
                if guard:
                    guard.register_secret(secret)
                key_name = scheme.name or "Authorization"
                if scheme.location == ParameterLocation.QUERY:
                    artifacts.query[key_name] = secret
                else:
                    artifacts.headers[key_name] = secret
            elif scheme.type in {AuthType.BEARER, AuthType.OAUTH2}:
                secret: str | None = None
                if scheme.type == AuthType.OAUTH2:
                    cached = self._token_cache.get(self._cache_key(scheme, operation.api_name))
                    if cached:
                        secret = cached[0]
                if not secret:
                    secret = self.resolve_secret(scheme, operation.api_name)
                if not secret:
                    continue
                if guard:
                    guard.register_secret(secret)
                token = secret if secret.lower().startswith("bearer ") else f"Bearer {secret}"
                artifacts.headers["Authorization"] = token
            elif scheme.type == AuthType.BASIC:
                creds = self._resolve_basic(scheme, operation.api_name)
                if not creds:
                    continue
                if guard:
                    guard.register_secret(creds[1])
                artifacts.basic = creds
                encoded = base64.b64encode(f"{creds[0]}:{creds[1]}".encode()).decode()
                artifacts.headers["Authorization"] = f"Basic {encoded}"
        return artifacts
