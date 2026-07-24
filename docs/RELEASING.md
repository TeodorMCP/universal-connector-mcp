# Releasing (maintainer notes)

## Publish a new version to PyPI

1. Bump `version` in `pyproject.toml` and in `server.json` (both `version` and `packages[0].version`).
2. Commit, then tag and push:

   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```

   The [release workflow](../.github/workflows/release.yml) builds the sdist/wheel and publishes to PyPI
   via [trusted publishing](https://docs.pypi.org/trusted-publishers/) (environment `pypi`, no API tokens).

## Publish to the official MCP Registry

Uses [server.json](../server.json); the `mcp-name` marker at the top of the README verifies PyPI ownership.

```bash
mcp-publisher login github   # device-flow login as TeodorMCP
mcp-publisher publish
```

See the [registry quickstart](https://modelcontextprotocol.io/registry/quickstart) for details.

## Publish to Smithery (stdio bundle)

Smithery's web form only accepts hosted HTTP servers; local stdio servers are published as an MCPB
bundle. Build the bundle from the `mcpb/` staging layout (manifest v0.3, `uvx` command), then submit
a release to `PUT https://api.smithery.ai/servers/teodormcp%2Funiversal-connector-mcp/releases`
(multipart: `payload` = StdioDeployPayload JSON with a `serverCard`, `bundle` = the `.mcpb` file;
Bearer key from `%APPDATA%\smithery\settings.json` after `smithery auth login`):

```bash
npx @anthropic-ai/mcpb pack mcpb dist/universal-connector-mcp.mcpb
```

Note: `smithery mcp publish` CLI currently fails with "No values to set" for stdio bundles; the
direct API call above works.

Server card metadata (display name, description, icon) is stored separately from releases:

```text
PATCH https://api.smithery.ai/servers/teodormcp%2Funiversal-connector-mcp
  JSON body: { displayName, description, homepage, repositoryUrl, license, iconUrl }
PUT   https://api.smithery.ai/servers/teodormcp%2Funiversal-connector-mcp/icon
  multipart file field: icon
```

Both take the same Bearer API key (Smithery dashboard -> API keys, stored in
`%APPDATA%\smithery\settings.json`). The public registry endpoint caches responses,
so changes can take a few minutes to appear.

## Directory submissions (one-time / occasional)

- [cursor.directory](https://cursor.directory)
- [mcp.so](https://mcp.so)
- [Smithery](https://smithery.ai)
- [PulseMCP](https://www.pulsemcp.com)
- PR to the community list in [`modelcontextprotocol/servers`](https://github.com/modelcontextprotocol/servers)

## Optional: Claude Desktop bundle

Build a one-click `.mcpb` bundle and attach it to the GitHub release:

```bash
mcp2mcpb universal-connector-mcp --registry pypi --mode complete
```
