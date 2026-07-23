"""Network-level SSRF protection: private-IP blocking and redirect-safe sends.

The host allowlist in :mod:`guard` decides *which names* are reachable; this
module makes sure a name (or a redirect) cannot resolve to an internal address
such as ``127.0.0.1``, ``10.0.0.0/8`` or the cloud metadata endpoint
``169.254.169.254``. Protection is best-effort against DNS rebinding (we resolve
and inspect every candidate address before the request, but do not pin the
socket to the resolved IP).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpx

from universal_connector.security.guard import SecurityError, SecurityGuard


def _address_blocked(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # covers 169.254.169.254 cloud metadata
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def assert_public_host(host: str) -> None:
    """Raise SecurityError if *host* resolves to any non-public address."""
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM
        )
    except socket.gaierror:
        # Unresolvable: let the real request fail with a normal network error.
        return
    for info in infos:
        addr = info[4][0]
        if _address_blocked(addr):
            raise SecurityError(
                f"Host '{host}' resolves to a private/internal address ({addr}); "
                f"blocked to prevent SSRF. Add it to UCMCP_ALLOWED_HOSTS to allow "
                f"internal targets, or set UCMCP_BLOCK_PRIVATE_IPS=false."
            )


async def _check_hop(guard: SecurityGuard, url: str, *, enforce_allowlist: bool) -> None:
    if enforce_allowlist:
        guard.check_url(url)
        host = httpx.URL(url).host
    else:
        host = guard.check_scheme(url)
    if guard.block_private_ips and not guard.host_explicitly_allowed(host):
        await assert_public_host(host)


async def guarded_send(
    client: httpx.AsyncClient,
    request: httpx.Request,
    guard: SecurityGuard,
    *,
    enforce_allowlist: bool,
) -> httpx.Response:
    """Send *request*, re-validating the guard on the initial URL and every redirect.

    The client MUST be created with ``follow_redirects=False`` so each hop can be
    inspected before it is followed.
    """
    req = request
    for _ in range(guard.max_redirects + 1):
        await _check_hop(guard, str(req.url), enforce_allowlist=enforce_allowlist)
        response = await client.send(req)
        if response.is_redirect and response.next_request is not None:
            await response.aread()
            req = response.next_request
            continue
        return response
    raise SecurityError(f"Exceeded {guard.max_redirects} redirects.")
