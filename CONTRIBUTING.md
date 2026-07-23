# Contributing

Contributions are welcome - from typo fixes to new protocol adapters.

## Dev setup

```bash
git clone https://github.com/TeodorMCP/universal-connector-mcp
cd universal-connector-mcp
pip install -e ".[all,dev]"
```

## Before you open a PR

```bash
pytest          # all tests must pass
ruff check .    # lint must be clean
```

CI runs both on Ubuntu and Windows with Python 3.10 and 3.12.

## What makes a good contribution

- **Bug fixes** - include a regression test that fails without the fix.
- **New protocol adapters** - subclass `SpecAdapter` (see `src/universal_connector/adapters/`),
  normalize everything into `Operation` objects, and add an executor if the protocol needs one.
  Keep optional dependencies behind an extra in `pyproject.toml`.
- **Catalog entries** - add verified, working spec URLs to `catalog.py` with correct `base_url`
  and auth hints. Test with a real `load_api` + `execute` before submitting.
- **Docs and examples** - walkthroughs of real workflows are highly valued.

## Security rules for all contributions

These are non-negotiable design constraints:

- No arbitrary code execution paths, no binary downloads, no telemetry.
- Outbound requests must go through the security guard (allowlist check).
- Secrets must never appear in logs, errors, audit entries or tool results.
- New settings default to the safe option.

Security issues go through [private reporting](SECURITY.md), not public issues.

## Style

- Python 3.10+, type hints everywhere, `ruff` clean.
- Keep the meta-tool surface small: prefer improving existing tools over adding new ones.
