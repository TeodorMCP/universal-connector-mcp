# Security Policy

Security is this project's core design goal, so security reports get top priority.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Instead use
[GitHub private vulnerability reporting](https://github.com/TeodorMCP/universal-connector-mcp/security/advisories/new):
Security tab -> Report a vulnerability.

You can expect an initial response within 72 hours. Please include reproduction steps and the
affected version.

## Scope

Reports we are especially interested in:

- Bypasses of the outbound host allowlist (SSRF and friends)
- Credential leakage into tool results, logs, audit entries or error messages
- Spec parsing issues that lead to unexpected outbound requests or resource exhaustion
- Cache poisoning across APIs or auth contexts

## Supported versions

Only the latest release receives security fixes.

## Design guarantees (what to test against)

- Outbound requests are restricted to hosts of explicitly loaded specs plus `UCMCP_ALLOWED_HOSTS`
- Secrets come from environment variables / OS keyring only, are injected at request time and
  redacted from logs, errors and audit entries
- No arbitrary code execution, no binary downloads, no telemetry
- Responses are size-capped before reaching the agent context
