# MCP Servers

StewardOS uses two MCP server classes:

- first-party servers maintained in this repository,
- upstream servers referenced via pinned commits/forks.

## First-Party MCP Servers (14 total)

### Domain Graph Servers (DB-backed)

| Server | Domain | Database |
|--------|--------|----------|
| `estate-planning-mcp` | Succession, trusts, entities, ownership, legal docs | `estate_planning.estate` |
| `finance-graph-mcp` | Illiquid assets, valuations, liabilities | `finance_graph.finance` |
| `health-graph-mcp` | Genomics, clinical assertions, labs, coverage | `health_graph.health_graph` |
| `household-tax-mcp` | US+MA tax engine (TY2025), itemized deductions, AMT, child tax credit | `household_tax.household_tax` |
| `family-edu-mcp` | Child education, CDC milestones, activity planning | `family_edu.family_edu` |

### API Wrapper Servers (thin HTTP)

| Server | Backend | Notes |
|--------|---------|-------|
| `ghostfolio-mcp` | Ghostfolio portfolio tracker | Read-only |
| `homebox-mcp` | Homebox inventory | HTTP envelope |
| `grocy-mcp` | Grocy pantry/shopping | HTTP envelope |
| `memos-mcp` | Memos note-taking | HTTP envelope |
| `wger-mcp` | wger workout/nutrition | Includes FitBod CSV import |
| `peloton-mcp` | Peloton workouts | OAuth PKCE, read-only |

### Project Management

| Server | Backend | Notes |
|--------|---------|-------|
| `plane-mcp` | Plane PM | 58 governance-safe tools across 12 modules, SDK + direct HTTP |

### Investment Workspace (multi-module)

`servers/investing-workspace/` contains 4 sub-modules under a single workspace:

| Module | Domain |
|--------|--------|
| `market-intel-direct` | yfinance market data, FRED macro, GDELT news, CFTC positioning |
| `portfolio-analytics` | Portfolio risk, drift, tax-loss harvesting, illiquid override |
| `policy-events` | Congressional bills, regulatory filings, policy impact |
| `sec-edgar` | SEC disclosures, insider forms, XBRL |

## Module Structure

Each DB-backed server follows the decomposition pattern:

- **`server.py`** — thin orchestrator that creates the `FastMCP` instance and registers domain modules
- **Domain modules** (e.g. `people.py`, `assets.py`) — each exports `register_<domain>_tools(mcp, get_pool)` containing `@mcp.tool()` decorated functions
- **`conftest.py`** in `tests/` — provides `FakeMCP` and `mock_asyncpg_pool` fixtures for database-free DI testing

### Plane-MCP Module Structure

`plane-mcp` uses the same decomposition pattern with 12 tool modules:

`discovery`, `creation`, `execution`, `projects`, `cycles`, `modules`, `pages`, `coordination`, `management`, `views`, `estimates`, `relations`

Shared helpers in `_helpers.py` (audit log, normalize, extract, work-item dict) and `_http.py` (direct HTTP for SDK gaps). All write tools validate `PLANE_HOME_WORKSPACE` — structural tools reject cross-workspace writes; execution tools allow cross-workspace for delegation.

## Shared Library (`servers/lib/`)

`stewardos-lib` contains domain logic shared across DB-backed servers: database utilities, constants, domain operations, graph documents, JSON validation, migrations, portfolio snapshots, and response formatting.

Consuming servers declare it as a local path dependency:

```toml
[tool.uv.sources]
stewardos-lib = { path = "../../servers/lib", editable = true }
```

## Framework Standard

All first-party servers use `from mcp.server.fastmcp import FastMCP` with the `mcp>=1.0.0` dependency. The legacy `fastmcp` package is not used.

## Wellness Integration Notes

- `health-records-mcp` is retired and replaced by `health-graph-mcp`.
- Peloton now uses OAuth Authorization Code + PKCE bootstrap with refresh-token operation for unattended runs.
- wger includes FitBod CSV parse/preview/import tooling and persistent mapping/import ledgers under `data/fitbod/`.
- Apple Health remains file-backed in current architecture; automated pull/sync is tracked as a roadmap item.

## Upstream MCP Servers

Upstream dependencies are not vendored in tracked content.
Use:

- `docs/upstreams/upstreams.lock.yaml`,
- `scripts/bootstrap_upstreams.sh`,
- `scripts/verify_upstreams.sh`.

## Fork Policy

When upstream MCP behavior is modified for StewardOS requirements:

1. maintain a fork under the repository owner namespace,
2. keep patch commits explicit and reviewable,
3. pin fork commit SHA in lockfile,
4. prefer upstream PRs where feasible.
