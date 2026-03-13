# MCP Servers

StewardOS uses MCP as the tool contract between personas/agents and the underlying software/data systems.

## Why this exists

MCP is the abstraction layer that keeps the operating model stable while applications, APIs, and providers evolve.

- Personas call tools, not raw APIs.
- Tooling is typed, auditable, and easier to test.
- Integration logic is centralized in server implementations instead of duplicated in prompts.

## What is currently configured

StewardOS currently uses a mixed server model:

- First-party domain servers in `servers/` (in-repo code, StewardOS-owned behavior).
- Upstream/forked servers pinned by commit in [`docs/upstreams/upstreams.lock.yaml`](../../upstreams/upstreams.lock.yaml).

### First-party server coverage (currently in repo)

#### Investment & Portfolio

| Server | Key Tools | Description |
|--------|-----------|-------------|
| `portfolio-analytics` | `analyze_portfolio_risk`, `get_condensed_portfolio_state`, `find_tax_loss_harvesting_candidates`, `analyze_allocation_drift`, `get_portfolio_return_series` | Risk modeling (Student-t ES, illiquid overlay, FX risk), portfolio state, TLH candidates, drift analysis |
| `market-intel-direct` | `get_market_snapshot`, `get_symbol_history`, `get_multi_asset_history`, `get_macro_context_panel`, `search_market_news`, `get_cftc_cot_snapshot` | Real-time market data, historical prices, FRED macro indicators, CFTC positioning, news search |
| `policy-events` | `get_recent_bills`, `get_federal_rules`, `get_upcoming_hearings`, `get_bill_details`, `get_rule_details`, `get_hearing_details` | Congressional bills, Federal Register rules, committee hearings (two-stage sieve pattern) |
| `ghostfolio-mcp` | `portfolio`, `account`, `order`, `market`, `reference`, `system` | Consolidated portfolio state, accounts, activities, market data from Ghostfolio |

> **Note on `ghostfolio-mcp`**: This server uses consolidated operation patterns (e.g., `portfolio(operation="summary")`, `account(operation="list")`) rather than one-tool-per-function. Each top-level tool dispatches to sub-operations via an `operation` parameter.

#### Estate & Finance

| Server | Key Tools | Description |
|--------|-----------|-------------|
| `estate-planning-mcp` | `get_ownership_graph`, `get_net_worth`, `upsert_entity`, `set_ownership`, `upsert_succession_plan`, `upsert_compliance_obligation`, `link_document` | Entity/asset/person graph, ownership chains, succession planning, compliance tracking, document linking |
| `finance-graph-mcp` | `get_net_worth`, `upsert_financial_statement_period`, `upsert_statement_line_items`, `record_valuation_observation`, `upsert_liability`, `analyze_refinance_npv`, `get_liability_summary` | Net worth roll-up, financial statement persistence, illiquid valuations, liability tracking, refinance analysis |
| `household-tax-mcp` | `compute_individual_return_exact`, `compute_fiduciary_return_exact`, `plan_individual_safe_harbor`, `plan_fiduciary_safe_harbor`, `compare_individual_payment_strategies`, `assess_exact_support`, `ingest_return_facts` | Exact 2025/2026 US+MA individual and fiduciary tax returns, safe-harbor planning, payment strategy comparison, golden-file-verified accuracy |

#### Household & Operations

| Server | Key Tools | Description |
|--------|-----------|-------------|
| `grocy-mcp` | `get_stock_overview`, `get_missing_products`, `get_shopping_list`, `consume_product`, `add_missing_to_shopping_list`, `get_expiring_products` | Pantry inventory, stock tracking, shopping list management, expiration monitoring |
| `homebox-mcp` | `list_items`, `create_item`, `get_item_maintenance`, `add_maintenance_entry`, `get_group_statistics`, `import_items_csv` | Home inventory, asset tracking, maintenance logs, location hierarchy |
| `memos-mcp` | `list_memos`, `create_memo`, `search_memos`, `list_memo_comments`, `upload_attachment` | Quick capture, notes, decision logs, attachments |
| `family-edu-mcp` | `get_learner_profile`, `record_observation`, `get_assessment_summary`, `create_weekly_activity_plan`, `recommend_activities_for_age`, `generate_term_brief` | Child development tracking, evidence pipeline, activity planning, assessment summaries |

#### Health & Wellness

| Server | Key Tools | Description |
|--------|-----------|-------------|
| `health-graph-mcp` | `ingest_clinical_assertions`, `query_variant_assertions`, `get_polygenic_context`, `get_wellness_recommendations`, `query_evidence_graph`, `ingest_23andme_genotypes`, `get_pgx_context` | Genome-aware health graph: 23andMe genotype ingestion, clinical variant assertions, pharmacogenomics, polygenic risk, lab results, and Paperless document sync — 27 tools across 10 modules |
| `wger-mcp` | `get_workout_log`, `get_nutrition_plan`, `get_body_weight`, `log_workout`, `log_nutrition_diary`, `get_nutrition_values` | Workout tracking, nutrition logging, body composition, macro calculations |
| `peloton-mcp` | `get_recent_rides`, `get_ride_details`, `get_workout_history`, `get_performance_metrics`, `get_achievements` | Peloton ride history, performance metrics, workout details |

#### Project Management

| Server | Key Tools | Description |
|--------|-----------|-------------|
| `plane-mcp` | `discover_work_items`, `create_work_item`, `update_work_item_status`, `create_page`, `search_pages`, `manage_cycle`, `manage_module`, `create_view`, `set_estimate`, `create_relation` | Governance-safe Plane PM wrapper — 59 tools across 12 modules (discovery, creation, execution, projects, cycles, modules, pages, coordination, management, views, estimates, relations). Write tools validate `PLANE_HOME_WORKSPACE`; structural tools reject cross-workspace writes while execution tools allow cross-workspace for delegation. |

### Pinned upstream/forked dependencies

The lockfile currently pins:

- `actual-mcp`
- `apple-health-mcp`
- `google-workspace-mcp`
- `mealie-mcp-server`
- `oura-mcp`
- `paperless-mcp`
- `sec-edgar-mcp`

Each entry includes remote/upstream URLs, checkout path, and exact commit SHA.

> **Note on `sec-edgar`**: The `sec-edgar` server used in the investing-workspace is the same codebase as the upstream `sec-edgar-mcp` fork, pinned via `upstreams.lock.yaml`. It is not a separate server.

### Persona access matrix

Each persona's AGENTS.md contract defines its MCP server access. The matrix below summarizes read/write authority across all 8 personas and 22 servers.

| Server | Portfolio Manager | Research Analyst | Comptroller | Estate Counsel | Director | Wellness Advisor | Insurance Advisor | Chief of Staff |
|--------|------------------|-----------------|-------------|----------------|----------|-----------------|-------------------|----------------|
| portfolio-analytics | **read-write** | — | — | — | — | — | — | — |
| market-intel-direct | read-only | read-only | — | — | — | — | — | — |
| ghostfolio | **read-write** | — | read-only | — | — | — | — | — |
| policy-events | read-only | read-only | — | — | — | — | — | — |
| sec-edgar | read-only | read-only | — | — | — | — | — | — |
| household-tax | read-only | — | **read-write** | — | — | — | — | — |
| finance-graph | read-only | read-only | **read-write** | read-only | — | — | read-only | — |
| estate-planning | — | — | read-only | **read-write** | — | — | read-only | — |
| actual | — | — | **read-write** | — | — | — | read-only | — |
| paperless | read-only | — | — | **read-write** | — | — | read-only | **read-write** |
| mealie | — | — | — | — | **read-write** | — | — | — |
| grocy | — | — | — | — | **read-write** | — | — | — |
| family-edu | — | — | — | — | **read-write** | — | — | — |
| homebox | — | — | — | — | **read-write** | — | — | — |
| wger | — | — | — | — | — | **read-write** | — | — |
| health-graph | — | — | — | — | — | **read-write** | — | — |
| peloton | — | — | — | — | — | read-only | — | — |
| oura | — | — | — | — | — | read-only | — | — |
| apple-health | — | — | — | — | — | read-only | — | — |
| memos | — | — | — | — | — | — | — | **read-write** |
| google-workspace | read-write | read-write | read-write | read-write | read-write | read-write | read-write | read-write |
| plane-pm | **read-write** | **read-write** | **read-write** | **read-write** | **read-write** | **read-write** | **read-write** | **read-write** |

## Dependency governance and reproducibility

### Source of truth

- [`docs/upstreams/upstreams.lock.yaml`](../../upstreams/upstreams.lock.yaml)

### Operational scripts

- [`scripts/bootstrap_upstreams.sh`](../../../scripts/bootstrap_upstreams.sh): clone/fetch and checkout locked commits.
- [`scripts/verify_upstreams.sh`](../../../scripts/verify_upstreams.sh): verify local checkouts match locked SHAs.

### Fork policy

1. Fork upstream when patches are required.
2. Keep patch deltas explicit and reviewable.
3. Pin exact commit SHA in the lockfile.
4. Prefer upstreaming generic improvements to reduce long-term fork maintenance.

## Workflows

See [README.md](../../../README.md#what-this-system-actually-does) for end-to-end workflow examples showing how MCP tools compose with personas and skills.

## Customization and extension

### Add a new first-party MCP server

1. Create a new server under `servers/<name>-mcp`.
2. Define stable tool names/inputs/outputs and document them in server README.
3. Add server wiring to the relevant persona config template in `agent-configs/*/.codex/config.toml.example`.
4. Update affected architecture/persona docs.

### Add or modify an upstream dependency

1. Add lock entry in [`upstreams.lock.yaml`](../../upstreams/upstreams.lock.yaml).
2. Run bootstrap and verify scripts.
3. Document why the dependency is needed and whether it is a fork.
4. If a fork is used, reference maintainer fork URL and pinned commit.

## Boundaries

- MCP servers define integration behavior and tool contracts.
- Personas define who can use which tools and under what constraints.
- Skills define procedural quality and expected output shape when tools are used.
