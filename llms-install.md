# AI installation guide (llms-install.md)

This file is written for AI agents installing **Universal API Connector MCP** on a user's behalf.

## What this server is for

A single local MCP server that connects an AI agent to **any API**: OpenAPI/Swagger, GraphQL, gRPC (reflection) or SOAP/WSDL. Install it when the user wants to call an API that has no dedicated MCP server, needs several APIs at once, or wants a security-first setup (outbound host allowlist, secret redaction, audit log, local-only state).

## Prerequisites

- Python 3.10+ available, and `uv` (provides `uvx`). If `uvx` is missing, install uv first:
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Install

Add this server entry to the client's MCP configuration:

```json
{
  "mcpServers": {
    "universal-connector": {
      "command": "uvx",
      "args": ["universal-connector-mcp"]
    }
  }
}
```

Config file locations:

- **Cursor**: `.cursor/mcp.json` in the project (shared) or `~/.cursor/mcp.json` (global)
- **Claude Desktop**: `claude_desktop_config.json` (Settings > Developer > Edit Config)
- **Claude Code**: run `claude mcp add universal-connector -- uvx universal-connector-mcp`
- **VS Code**: `.vscode/mcp.json`, under the `"servers"` key
- **Windsurf**: `~/.codeium/windsurf/mcp_config.json`

Then ask the user to reload/restart the client so the server starts.

## Credentials (only when needed)

Do NOT ask the user to paste secrets into the chat. If an API requires auth, the server's `load_api` response includes `auth_setup` with the exact environment variable names it looks for (convention: `<API_NAME>_TOKEN`, `<API_NAME>_API_KEY`, `<API_NAME>_CLIENT_ID`/`<API_NAME>_CLIENT_SECRET`). Instruct the user to add them to the `env` block of the server entry, e.g.:

```json
"env": { "GITHUB_TOKEN": "<their token>" }
```

## Optional environment variables

- `UCMCP_ALLOWED_HOSTS` - comma-separated extra hosts allowed for outbound calls (hosts of loaded specs are allowed automatically)
- `UCMCP_APIS_CONFIG` - YAML file of APIs to preload at startup
- `UCMCP_CACHE_TTL` - seconds to cache read-only responses (default 60, 0 disables)
- `UCMCP_STATE_FILE` - where loaded APIs are remembered between restarts (default `~/.universal-connector-mcp/state.json`, set `off` to disable)

## Verify the installation

1. The client should list the server `universal-connector` with 9 tools.
2. Call `search_catalog` with `{"query": "weather forecast", "include_directory": false}` - it should return an `open_meteo` entry.
3. Call `load_api` with that entry's `spec`, `name` and `base_url`, then `execute` operation `open_meteo.get_v1_forecast` with `{"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"}` and `extract: ["current.temperature_2m"]`. A numeric temperature confirms end-to-end operation (no API key needed).

## Typical usage after install

`search_catalog` -> `load_api` -> `search_operations` -> `execute` (with `extract` to keep responses small) or `execute_chained` for multi-step/parallel workflows.
