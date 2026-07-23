# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-07-23

### Added

- **`execute_graph` meta-tool**: run a dependency graph (DAG) of operations in a
  single call. Execution order is inferred automatically from `${id.path}`
  references between nodes (plus optional `depends_on`), and independent nodes
  run concurrently (bounded by `max_concurrency`). Cycles and dangling references
  are rejected up front; a failed node's dependents are skipped while independent
  branches continue. Complements `execute_chained` (which stays for simple linear
  sequences).

## [0.1.1] - 2026-07-23

Security hardening release. Closes SSRF vectors reported in early code review.

### Security

- **SSRF protection**: outbound requests (including spec fetches and GraphQL
  introspection) now block hosts that resolve to private, loopback, link-local,
  reserved or cloud-metadata (`169.254.169.254`) addresses. Reaching an internal
  address requires an explicit `UCMCP_ALLOWED_HOSTS` entry or
  `UCMCP_BLOCK_PRIVATE_IPS=false`. Disabling the allowlist (`UCMCP_ALLOW_ALL_HOSTS`)
  no longer opens the internal network.
- **Redirect safety**: HTTP redirects are followed manually and every hop is
  re-validated against the allowlist and the private-IP check, so a redirect can
  no longer escape to a blocked host. Redirect count is capped (`UCMCP_MAX_REDIRECTS`).
- **Spec-fetch guard**: `load_api` spec downloads and GraphQL introspection now go
  through the security guard instead of an unchecked client.
- **SOAP imports**: the WSDL is loaded from already-fetched content and remote
  WSDL/XSD imports are routed through a transport that blocks private-IP targets.

### Added

- `UCMCP_BLOCK_PRIVATE_IPS` (default `true`) and `UCMCP_MAX_REDIRECTS` (default `5`) settings.

## [0.1.0] - 2026-07-23

First public release.

### Added

- Universal spec adapters: OpenAPI 3.x / Swagger 2.0, GraphQL (introspection or SDL),
  gRPC (server reflection, unary-unary), SOAP (WSDL) - all normalized into one `Operation` model.
- 9 meta-tools: `search_catalog`, `load_api`, `list_apis`, `search_operations`, `get_operation`,
  `execute`, `execute_chained`, `unload_api`, `audit_log`.
- Built-in API catalog: curated list of popular APIs plus the APIs.guru directory (2500+ specs).
- Context efficiency: field-level response filtering (`extract` with `*` wildcards), chained
  execution with `${step.path}` piping, parallel step groups, TTL response cache for reads.
- Security: outbound host allowlist, secret redaction, response size caps, audit log,
  no code execution, no telemetry.
- Auth: environment-variable and OS-keyring credential resolution (API key, bearer, basic,
  OAuth2 client credentials) with per-API setup hints in `load_api` responses.
- Session persistence: loaded APIs (spec locations only) are remembered across restarts.
- Distribution: PyPI package (`uvx universal-connector-mcp`), official MCP Registry entry,
  MCPB bundle, Open Plugins manifest.

[0.2.0]: https://github.com/TeodorMCP/universal-connector-mcp/releases/tag/v0.2.0
[0.1.1]: https://github.com/TeodorMCP/universal-connector-mcp/releases/tag/v0.1.1
[0.1.0]: https://github.com/TeodorMCP/universal-connector-mcp/releases/tag/v0.1.0
