# Contributing to StewardOS

## User Contributions

StewardOS is built for people who manage their own affairs — portfolio, household budget, health, estate — and have developed practical expertise doing it. The most valuable contributions encode real workflows as skills.

### Contributing a skill (no local setup required)

Skills are markdown files. You can contribute one without cloning the repo or running the stack:

1. **Pick your persona**: choose the role that matches your expertise
   - Managing portfolios → [Portfolio Manager](agent-configs/investment-officer/AGENTS.md)
   - Investment research & analysis → [Research Analyst](agent-configs/research-analyst/AGENTS.md)
   - Running household finances → [Household Comptroller](agent-configs/household-comptroller/AGENTS.md)
   - Handling estate/legal matters → [Estate Counsel](agent-configs/estate-counsel/AGENTS.md)
   - Running household logistics → [Household Director](agent-configs/household-director/AGENTS.md)
   - Tracking health/fitness → [Wellness Advisor](agent-configs/wellness-advisor/AGENTS.md)
   - Managing insurance → [Insurance Advisor](agent-configs/insurance-advisor/AGENTS.md)
   - Coordinating across domains → [Chief of Staff](agent-configs/chief-of-staff/AGENTS.md)

2. **Read 2-3 existing skills** in `skills/personas/<persona>/` to understand the structure

3. **Write your skill** following the [Skill Contribution Guide](docs/community/skill-contribution-guide.md) — includes an annotated example, tool reference tables, and a PR checklist

4. **Submit via GitHub**: create your `skills/personas/<persona>/<skill-name>/SKILL.md` file and open a PR

### Sanitization checklist (all contributions)

Before submitting any contribution, verify it contains none of the following:

- [ ] Personal names, email addresses, or email aliases
- [ ] Domain names, URLs, or IP addresses specific to a deployment
- [ ] Account IDs, API keys, tokens, or credentials
- [ ] File paths that include usernames or deployment-specific directories
- [ ] References to specific financial accounts, portfolio holdings, or tax details

## Development Contributions

### Getting started

1. Clone the repository.
2. Copy required `*.example` files to local runtime equivalents.
3. Bootstrap upstream MCP dependencies:
   ```bash
   scripts/bootstrap_upstreams.sh
   ```
4. Verify pinned checkouts:
   ```bash
   scripts/verify_upstreams.sh
   ```

### Shared Library (`servers/lib/`)

Duplicated domain logic lives in `stewardos-lib`. When adding shared functions:

- Pure helpers → `constants.py` or `json_utils.py`
- Database operations → `domain_ops.py` (accept `asyncpg.Pool`, return `asyncpg.Record`)
- Add tests in `servers/lib/tests/`

Consuming servers use a local path dep — see [`servers/lib/README.md`](servers/lib/README.md).

### Server Decomposition

DB-backed servers use the `register_<domain>_tools(mcp, get_pool)` pattern:

- `server.py` is a thin orchestrator — no tool logic inline
- Each domain module registers its tools via the decorator pattern
- Tests use `FakeMCP` + `mock_asyncpg_pool` from `tests/support/`

### Testing

```bash
make test-all        # run all project test suites
make test-server NAME=health-graph-mcp  # run one server
make lint            # ruff check
make verify-skills   # skill-to-tool contract verification
```

Tests run per-project via `uv run --extra dev pytest tests/ -v`. Add `pytest` (and `pytest-asyncio` for async tests) to `[project.optional-dependencies] dev` in each server's `pyproject.toml`.

### Sensitive files

Do not commit:

- live `.env` files
- runtime `.codex` state
- OAuth credential/token files
- local database or log artifacts

Use sanitized `*.example` files for any new configuration.

### Pull request guidelines

- Keep changes scoped and documented.
- Update architecture docs when behavior or boundaries change.
- Include migration notes for any configuration contract change.
- Preserve anonymization in public-facing examples and docs.
- For persona/skill changes, include concrete before/after examples and rationale.
