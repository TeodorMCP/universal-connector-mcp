# Step-by-step examples

Real workflows, exactly as an agent executes them. Every example works with the default install
(`uvx universal-connector-mcp`); none of them require editing config files by hand.

In practice you don't type these calls yourself - you ask your agent in plain language
("what's the weather in Berlin?") and it makes these calls. The transcripts below show what
happens under the hood, so you can debug and build intuition.

## 1. Weather in one call chain (no API key)

Ask your agent: *"What's the current temperature in Berlin?"*

```text
search_catalog(query="weather forecast")
-> [{"name": "open_meteo", "spec": "https://.../openapi/forecast.yml",
    "base_url": "https://api.open-meteo.com", "auth": "none", ...}]

load_api(spec="https://.../openapi/forecast.yml", name="open_meteo",
         base_url="https://api.open-meteo.com")
-> {"name": "open_meteo", "operations": 1, ...}

execute(operation_id="open_meteo.get_v1_forecast",
        params={"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"},
        extract=["current.temperature_2m"])
-> {"ok": true, "data": {"current.temperature_2m": 19.1}}
```

Note the `extract`: instead of a multi-kilobyte forecast JSON, the agent's context receives
one number.

## 2. GitHub with a token

Ask your agent: *"Connect the GitHub API and list my repos."*

```text
search_catalog(query="github")
load_api(spec="https://raw.githubusercontent.com/github/rest-api-description/main/descriptions/api.github.com/api.github.com.json",
         name="github")
-> {..., "auth_setup": {"configured": false,
      "hint": "Set GITHUB_TOKEN in the env block of your MCP config"}}
```

The `auth_setup` block tells the agent (and you) exactly what is missing. Add the variable to
your MCP client config and restart:

```json
{
  "mcpServers": {
    "universal-connector": {
      "command": "uvx",
      "args": ["universal-connector-mcp"],
      "env": { "GITHUB_TOKEN": "ghp_your_token_here" }
    }
  }
}
```

Then:

```text
search_operations(query="list repositories for authenticated user", api="github")
execute(operation_id="github.repos_list_for_authenticated_user",
        params={"per_page": 10}, extract=["*.full_name", "*.stargazers_count"])
```

The token never appears in chat, logs or audit entries - it lives only in the config file.

## 3. GraphQL with field selection

Ask your agent: *"Which currency does Brazil use?"*

```text
load_api(spec="https://countries.trevorblades.com/", protocol="graphql", name="countries")
execute(operation_id="countries.country",
        params={"code": "BR", "fields": "name capital currency"})
-> {"ok": true, "data": {"country": {"name": "Brazil", "capital": "Brasília", "currency": "BRL"}}}
```

For GraphQL, `fields` controls the selection set - the query asks the server for exactly those
fields, so filtering happens before the response is even generated.

## 4. Multi-API workflow in a single tool call

Ask your agent: *"Compare the stars of two repos and get Berlin weather, all at once."*

```text
execute_chained(steps=[
  [
    {"operation_id": "github.repos_get", "params": {"owner": "python", "repo": "cpython"},
     "save_as": "py", "extract": ["stargazers_count"]},
    {"operation_id": "github.repos_get", "params": {"owner": "rust-lang", "repo": "rust"},
     "save_as": "rs", "extract": ["stargazers_count"]},
    {"operation_id": "open_meteo.get_v1_forecast",
     "params": {"latitude": 52.52, "longitude": 13.41, "current": "temperature_2m"},
     "save_as": "berlin", "extract": ["current.temperature_2m"]}
  ]
])
```

The inner list is a **parallel group**: all three requests run concurrently, and the agent gets
three tiny results in one round-trip instead of three full tool calls.

Piping results between steps uses `${save_as.path}` references:

```text
execute_chained(steps=[
  {"operation_id": "github.repos_list_for_user", "params": {"username": "torvalds"},
   "save_as": "repos"},
  {"operation_id": "github.repos_get",
   "params": {"owner": "torvalds", "repo": "${repos.data.0.name}"},
   "extract": ["description", "stargazers_count"]}
])
```

## 5. Your own internal API

Any spec source works - URL, local file, or raw content:

```text
load_api(spec="file:///C:/work/billing/openapi.yaml", name="billing",
         base_url="https://billing.internal.example.com")
```

Only `billing.internal.example.com` gets added to the outbound allowlist - the server still
refuses to call anything else. Credentials follow the same convention: set
`BILLING_TOKEN` / `BILLING_API_KEY` in the config `env` block.

**Internal / private-network hosts**: SSRF protection blocks addresses that resolve to
private, loopback or link-local IPs by default. To reach an internal API, add its host to
`UCMCP_ALLOWED_HOSTS` (this is the explicit opt-in that lifts the private-IP block for that host):

```json
{ "env": { "UCMCP_ALLOWED_HOSTS": "billing.internal.example.com" } }
```

Alternatively set `UCMCP_BLOCK_PRIVATE_IPS=false` to disable the check globally (not recommended).

## Debugging tips

- `audit_log()` shows the last outbound calls: method, host, path, status - never bodies or secrets.
- Truncated response? The result's `note` suggests an `extract` - name the fields you need.
- Stale data? Reads are cached for `UCMCP_CACHE_TTL` seconds (default 60); pass `fresh: true`.
- `list_apis()` shows what is loaded; loaded APIs survive restarts (see
  [session persistence](../README.md#session-persistence)).
