import pytest

from universal_connector.config import Config
from universal_connector.security.guard import SecurityError, SecurityGuard


def test_denies_unregistered_host_by_default():
    guard = SecurityGuard(Config())
    with pytest.raises(SecurityError):
        guard.check_url("https://evil.example.com/steal")


def test_allows_registered_host():
    guard = SecurityGuard(Config())
    guard.register_hosts(["api.demo.test"])
    guard.check_url("https://api.demo.test/v1/pets")  # no raise


def test_explicit_allowlist():
    guard = SecurityGuard(Config(allowed_hosts=["api.github.com"]))
    guard.check_url("https://api.github.com/user")
    with pytest.raises(SecurityError):
        guard.check_url("https://api.gitlab.com/user")


def test_denylist_overrides_allow_all():
    guard = SecurityGuard(Config(allow_all_hosts=True, denied_hosts=["metadata.google.internal"]))
    guard.check_url("https://anything.example.com/")  # allowed
    with pytest.raises(SecurityError):
        guard.check_url("http://metadata.google.internal/")


def test_blocks_non_web_scheme():
    guard = SecurityGuard(Config(allow_all_hosts=True))
    with pytest.raises(SecurityError):
        guard.check_url("file:///etc/passwd")


def test_secret_redaction():
    guard = SecurityGuard(Config())
    guard.register_secret("supersecrettoken123")
    out = guard.redact("Authorization used supersecrettoken123 here")
    assert "supersecrettoken123" not in out
    assert "REDACTED" in out


def test_response_capping():
    guard = SecurityGuard(Config(max_response_bytes=10))
    capped, truncated = guard.cap_response("0123456789ABCDEF")
    assert truncated is True
    assert len(capped.encode("utf-8")) <= 10
