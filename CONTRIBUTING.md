# Contributing to StewardOS

## Development Model

This repository is an integration architecture. Contributions should prioritize:

- clear boundaries between persona capabilities,
- safe defaults for self-hosted deployments,
- reproducible MCP dependency pinning,
- documented operational behavior.

## Getting Started

1. Clone the repository.
2. Copy required `*.example` files to local runtime equivalents.
3. Bootstrap upstream MCP dependencies:
   - `scripts/bootstrap_upstreams.sh`
4. Verify pinned checkouts:
   - `scripts/verify_upstreams.sh`

## Sensitive Files

Do not commit:

- live `.env` files,
- runtime `.codex` state,
- OAuth credential/token files,
- local database or log artifacts.

Use sanitized `*.example` files.

## Shared Library (`servers/lib/`)

Duplicated domain logic lives in `stewardos-lib`. When adding shared functions:

- Pure helpers -> `constants.py` or `json_utils.py`
- Database operations -> `domain_ops.py` (accept `asyncpg.Pool`, return `asyncpg.Record`)
- Add tests in `servers/lib/tests/`

Consuming servers use a local path dep — see [`servers/lib/README.md`](servers/lib/README.md).

## Shared Agent Library (`agents/lib/`)

Cross-agent utilities live in `agents/lib/`:

- `gmail_watch.py` — Gmail watch API helpers
- `pubsub_validation.py` — Pub/Sub message validation
- `schedule_loader.py` — YAML schedule loading for APScheduler

## Server Decomposition

DB-backed servers use the `register_<domain>_tools(mcp, get_pool)` pattern:

- `server.py` is a thin orchestrator — no tool logic inline
- Each domain module registers its tools via the decorator pattern
- Tests use `FakeMCP` + `mock_asyncpg_pool` from `test_support/`

The same pattern applies to `plane-mcp` with 12 tool modules and `get_client()` DI.

## Testing

```bash
make test-all        # 411 tests across 19 projects
make test-server NAME=health-graph-mcp  # run one server
make lint            # ruff check
make verify-skills   # skill-to-tool contract verification
```

Tests run per-project via `uv run --extra dev pytest tests/ -v`. Add `pytest` (and `pytest-asyncio` for async tests) to `[project.optional-dependencies] dev` in each server's `pyproject.toml`.

## Persona and Skill Contributions

- Each persona config lives in `agent-configs/<persona>/AGENTS.md`
- Skills live in `skills/personas/<persona>/` (persona-specific) or `skills/shared/` (cross-domain)
- Skill-to-tool contracts are verified by CI (`make verify-skills`)
- See [Agent Personas](docs/architecture/agent-personas/README.md) for the 8-persona model
- See [Agent Skills](docs/architecture/agent-skills/README.md) for skill design guidelines

## Pull Request Guidelines

- Keep changes scoped and documented.
- Update architecture docs when behavior or boundaries change.
- Include migration notes for any configuration contract change.
- Preserve anonymization in public-facing examples and docs.
