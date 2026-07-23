"""SSRF protection: private-IP blocking and redirect re-checking."""

import httpx
import pytest

from universal_connector.config import Config
from universal_connector.security import net
from universal_connector.security.guard import SecurityError, SecurityGuard


def _fake_resolver(mapping):
    def _getaddrinfo(host, *args, **kwargs):
        addr = mapping.get(host)
        if addr is None:
            import socket

            raise socket.gaierror(f"unknown host {host}")
        return [(2, 1, 6, "", (addr, 0))]

    return _getaddrinfo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addr",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "0.0.0.0"],
)
async def test_assert_public_host_blocks_internal(monkeypatch, addr):
    monkeypatch.setattr(net.socket, "getaddrinfo", _fake_resolver({"target": addr}))
    with pytest.raises(SecurityError):
        await net.assert_public_host("target")


@pytest.mark.asyncio
async def test_assert_public_host_allows_public(monkeypatch):
    monkeypatch.setattr(net.socket, "getaddrinfo", _fake_resolver({"api.demo.test": "93.184.216.34"}))
    await net.assert_public_host("api.demo.test")  # no raise


@pytest.mark.asyncio
async def test_assert_public_host_ignores_unresolvable(monkeypatch):
    monkeypatch.setattr(net.socket, "getaddrinfo", _fake_resolver({}))
    await net.assert_public_host("nope.invalid")  # no raise; real request will fail


def test_explicit_allowlist_gates_private_bypass():
    guard = SecurityGuard(Config(allowed_hosts=["internal.corp"]))
    assert guard.host_explicitly_allowed("internal.corp") is True
    # A spec-derived host does not count as explicitly allowed.
    guard.register_hosts(["registered.corp"])
    assert guard.host_explicitly_allowed("registered.corp") is False


@pytest.mark.asyncio
async def test_guarded_send_rechecks_redirect_host(monkeypatch):
    """A redirect to a non-allowlisted host must be blocked mid-chain."""
    guard = SecurityGuard(Config(allowed_hosts=["good.test"]))
    monkeypatch.setattr(
        net.socket,
        "getaddrinfo",
        _fake_resolver({"good.test": "93.184.216.34", "evil.test": "93.184.216.35"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.test":
            return httpx.Response(302, headers={"location": "https://evil.test/steal"})
        return httpx.Response(200, text="reached evil")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        request = client.build_request("GET", "https://good.test/start")
        with pytest.raises(SecurityError):
            await net.guarded_send(client, request, guard, enforce_allowlist=True)


@pytest.mark.asyncio
async def test_guarded_send_blocks_redirect_to_private_ip(monkeypatch):
    """Allowlisted first host redirecting to an internal IP is blocked."""
    guard = SecurityGuard(Config(allow_all_hosts=True))
    monkeypatch.setattr(
        net.socket,
        "getaddrinfo",
        _fake_resolver({"public.test": "93.184.216.34", "metadata.test": "169.254.169.254"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.test":
            return httpx.Response(302, headers={"location": "http://metadata.test/latest/meta-data/"})
        return httpx.Response(200, text="secrets")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        request = client.build_request("GET", "https://public.test/")
        with pytest.raises(SecurityError):
            await net.guarded_send(client, request, guard, enforce_allowlist=False)


@pytest.mark.asyncio
async def test_guarded_send_follows_allowed_redirect(monkeypatch):
    guard = SecurityGuard(Config(allow_all_hosts=True))
    monkeypatch.setattr(
        net.socket,
        "getaddrinfo",
        _fake_resolver({"a.test": "93.184.216.34", "b.test": "93.184.216.35"}),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.test":
            return httpx.Response(302, headers={"location": "https://b.test/final"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        request = client.build_request("GET", "https://a.test/")
        resp = await net.guarded_send(client, request, guard, enforce_allowlist=False)
    assert resp.status_code == 200
    assert resp.text == "ok"


@pytest.mark.asyncio
async def test_load_api_blocks_spec_fetch_to_private_ip(monkeypatch):
    """load_api must refuse to fetch a spec from an internal address."""
    from universal_connector.tools import ConnectorService

    service = ConnectorService(Config())
    monkeypatch.setattr(net.socket, "getaddrinfo", _fake_resolver({"internal.host": "127.0.0.1"}))
    with pytest.raises(SecurityError):
        await service.load_api(spec="http://internal.host/openapi.json", name="x")
