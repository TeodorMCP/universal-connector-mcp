# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

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

[0.1.0]: https://github.com/TeodorMCP/universal-connector-mcp/releases/tag/v0.1.0
