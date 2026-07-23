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
