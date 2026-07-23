"""Distribution status dashboard: check every channel with one command.

Usage: python scripts/status.py
"""

from __future__ import annotations

import sys

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

import httpx

REPO = "TeodorMCP/universal-connector-mcp"
PACKAGE = "universal-connector-mcp"
REGISTRY_NAME = "io.github.TeodorMCP/universal-connector-mcp"
SMITHERY_PAGE = "https://smithery.ai/server/teodormcp/universal-connector-mcp"

client = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "ucmcp-status"})


def line(channel: str, status: str, detail: str = "") -> None:
    print(f"{channel:<16} {status:<8} {detail}")


def check_github() -> None:
    r = client.get(f"https://api.github.com/repos/{REPO}")
    if r.status_code != 200:
        line("GitHub", "ERROR", f"HTTP {r.status_code}")
        return
    d = r.json()
    line("GitHub", "OK", f"stars={d['stargazers_count']} forks={d['forks_count']} issues={d['open_issues_count']}")
    runs = client.get(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=1").json()
    if runs.get("workflow_runs"):
        w = runs["workflow_runs"][0]
        line("  last CI", w["conclusion"] or w["status"], w["name"])


def check_pypi() -> None:
    r = client.get(f"https://pypi.org/pypi/{PACKAGE}/json")
    if r.status_code != 200:
        line("PyPI", "ERROR", f"HTTP {r.status_code}")
        return
    line("PyPI", "OK", f"version={r.json()['info']['version']}")
    stats = client.get(f"https://pypistats.org/api/packages/{PACKAGE}/recent")
    if stats.status_code == 200:
        d = stats.json()["data"]
        line("  downloads", "OK", f"day={d['last_day']} week={d['last_week']} month={d['last_month']}")
    else:
        line("  downloads", "WAIT", "pypistats has no data yet (lags ~1-2 days)")


def check_registry() -> None:
    r = client.get("https://registry.modelcontextprotocol.io/v0/servers?search=universal-connector")
    if r.status_code != 200:
        line("MCP Registry", "ERROR", f"HTTP {r.status_code}")
        return
    for s in r.json().get("servers", []):
        srv = s.get("server", s)
        if srv.get("name") == REGISTRY_NAME:
            meta = s.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {})
            line("MCP Registry", meta.get("status", "?").upper(), f"v{srv.get('version')}")
            return
    line("MCP Registry", "MISSING", "not found in search")


def check_smithery() -> None:
    r = client.get(SMITHERY_PAGE)
    line("Smithery", "OK" if r.status_code == 200 else "WAIT", f"HTTP {r.status_code} {SMITHERY_PAGE}")


def check_pulsemcp() -> None:
    r = client.get("https://www.pulsemcp.com/servers", params={"q": PACKAGE})
    if r.status_code != 200:
        line("PulseMCP", "ERROR", f"HTTP {r.status_code}")
        return
    if "TeodorMCP" in r.text:
        line("PulseMCP", "LISTED", "found in site search")
    else:
        line("PulseMCP", "WAIT", "submission under review / not indexed yet")


def main() -> int:
    for check in (check_github, check_pypi, check_registry, check_smithery, check_pulsemcp):
        try:
            check()
        except Exception as exc:  # noqa: BLE001 - a dashboard must not die on one channel
            line(check.__name__.removeprefix("check_"), "ERROR", str(exc)[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
