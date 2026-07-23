# Marketing copy kit

Ready-to-paste texts for every distribution channel. Repository: https://github.com/TeodorMCP/universal-connector-mcp

## Tagline (banner, social preview)

> Any API. One MCP server.

## GitHub "About" (short description, <= 120 chars)

> Security-first MCP server that connects any OpenAPI, GraphQL, gRPC or SOAP API to AI agents. Any API. One server.

Topics: `mcp` `model-context-protocol` `openapi` `graphql` `grpc` `soap` `ai-agents` `cursor` `claude` `api-client` `security`

## One-paragraph description (mcp.so, Smithery, PulseMCP, cursor.directory)

> Universal API Connector turns any API into agent tools - without writing integration code. Load an OpenAPI/Swagger, GraphQL, gRPC or SOAP spec (or pick one from the built-in catalog of 2500+ public APIs) and the agent discovers and calls operations through 9 meta-tools instead of hundreds of per-endpoint tools. Field-level response filtering, chained/parallel execution and response caching keep workflows to a single tool call and responses small. Security-first by design: outbound host allowlist, secret redaction, size-capped responses and a full audit log. Local-first: no telemetry, no code execution, no binary downloads.

## Elevator pitch (long-form: blog intro, submission forms with room)

> Every service you connect to an AI agent usually means installing another MCP server - each shipping dozens of tools that eat your context window, each with its own quality and security story. Universal API Connector replaces the pile with one server: point it at any API description (OpenAPI, GraphQL, gRPC, SOAP) and every operation becomes callable through a small, fixed set of meta-tools. The agent explores an API like a filesystem: search operations, inspect the one it needs, execute it.
>
> It is built for context efficiency. `extract` returns only the response fields you name instead of multi-kilobyte payloads. `execute_chained` pipes results between calls - including parallel groups - so "query three services and combine" is one tool call. Successful reads are cached, so repeats are instant and free.
>
> And it is built for trust, as a direct response to MCP supply-chain attacks: outbound requests are restricted to an allowlist of loaded-spec hosts, credentials stay in environment variables and are redacted from every log and error, responses are size-capped, and every outbound call lands in an audit log. No arbitrary code execution, no downloads, no telemetry.

## Show HN draft

Title: `Show HN: One MCP server that connects AI agents to any API (OpenAPI/GraphQL/gRPC/SOAP)`

> Hi HN! We got tired of installing a separate MCP server for every service - each one dumping 50+ tools into the agent's context - so we built a universal connector instead.
>
> You point it at an API spec (or search its built-in catalog: a curated list plus the APIs.guru directory, 2500+ public OpenAPI specs) and the agent gets 9 meta-tools: search the catalog, load an API, search/inspect operations, execute. It works with OpenAPI, GraphQL, gRPC (server reflection) and SOAP through one normalized operation model.
>
> The interesting parts: field-level response filtering (`extract=["items.*.name"]` returns just that), chained execution with `${step.path}` references and parallel groups (whole multi-API workflows in one tool call), and a short-TTL cache for reads. Security was a design constraint from day one after the recent MCP supply-chain attacks: outbound allowlist, secret redaction, response caps, audit log, no code execution, no telemetry.
>
> Python, MIT-licensed, runs locally over stdio: `uvx universal-connector-mcp`. Feedback very welcome!

## Reddit r/mcp post draft

Title: `I built one MCP server that talks to any API (OpenAPI/GraphQL/gRPC/SOAP) - with response filtering so it doesn't eat your context`

> The problem: every API = another MCP server = another 50 tools in context, another supply-chain risk.
>
> My take on it: a single connector with 9 meta-tools. `search_catalog` finds a spec (curated list + APIs.guru, 2500+ APIs), `load_api` registers it, `search_operations`/`get_operation` explore it like a filesystem, `execute` calls it.
>
> What I think makes it different:
> - `extract` - name the fields you want, get only those back (huge token saver)
> - `execute_chained` - pipe results between calls, run independent calls in parallel: one tool call for a whole workflow
> - security-first: outbound host allowlist, secrets redacted everywhere, size caps, audit log
> - protocols beyond REST: GraphQL, gRPC via reflection, SOAP/WSDL
>
> MIT, local-first, `uvx universal-connector-mcp`. Would love feedback on the meta-tool ergonomics.

## X/Twitter post

> Stop installing an MCP server per API.
>
> Universal API Connector: one server, any API (OpenAPI/GraphQL/gRPC/SOAP), 2500+ specs in the built-in catalog.
>
> Returns only the fields you ask for. Chains + parallelizes calls. Allowlists every outbound host.
>
> `uvx universal-connector-mcp`

## Feature bullets (reuse anywhere)

- Any protocol: OpenAPI/Swagger, GraphQL, gRPC (reflection), SOAP/WSDL - one normalized model
- Built-in catalog: curated popular APIs + APIs.guru directory (2500+ specs), searchable by keywords
- `extract`: field-level response filtering - only the data you asked for reaches the context
- `execute_chained`: multi-step workflows with `${step.path}` piping and parallel groups in one tool call
- Response cache with TTL: repeated reads are instant and free
- Security-first: outbound allowlist, secret redaction, response size caps, audit log
- Local-first: stdio, no telemetry, no code execution, MIT

## Screenshot / demo ideas (for later)

1. GIF: agent in Cursor runs `search_catalog("weather")` -> `load_api` -> `execute` with `extract` and answers in ~15 seconds.
2. Side-by-side tokens: full forecast JSON (~4 KB) vs `extract` result (2 lines).
3. The banner (`assets/banner.png`) doubles as the GitHub social preview image (Settings -> General -> Social preview).
