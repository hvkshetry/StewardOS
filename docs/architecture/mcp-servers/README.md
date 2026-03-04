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

#### Estate & Finance

| Server | Key Tools | Description |
|--------|-----------|-------------|
| `estate-planning-mcp` | `get_ownership_graph`, `get_net_worth`, `upsert_entity`, `set_ownership`, `upsert_succession_plan`, `upsert_compliance_obligation`, `link_document` | Entity/asset/person graph, ownership chains, succession planning, compliance tracking, document linking |
| `finance-graph-mcp` | `get_net_worth`, `upsert_financial_statement_period`, `upsert_statement_line_items`, `record_valuation_observation`, `upsert_liability`, `analyze_refinance_npv`, `get_liability_summary` | Net worth roll-up, financial statement persistence, illiquid valuations, liability tracking, refinance analysis |
| `household-tax-mcp` | `evaluate_scenario`, `compare_scenarios`, `optimize_strategy`, `ingest_returns`, `upsert_tax_profile`, `filing_readiness_report` | 12-scenario tax optimization, multi-year simulation, return ingestion, filing readiness |

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
| `health-records-mcp` | `search_medical_documents`, `get_recent_lab_results`, `list_prescriptions`, `get_documents_by_provider`, `upload_medical_document` | Medical document management via Paperless-ngx with auto-tagging and provider tracking |
| `wger-mcp` | `get_workout_log`, `get_nutrition_plan`, `get_body_weight`, `log_workout`, `log_nutrition_diary`, `get_nutrition_values` | Workout tracking, nutrition logging, body composition, macro calculations |

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

## How this layer participates in workflows

### 1. Investment workflow

1. `ghostfolio` and portfolio tools provide holdings/risk context.
2. `policy-events` and `sec-edgar` provide policy/disclosure context.
3. Persona composes recommendations with explicit provenance to tool calls.

### 2. Estate workflow

1. Estate counsel queries ownership/entity graph via estate servers.
2. Paperless tools provide document evidence and IDs.
3. Finance graph data can be referenced without leaking write authority across roles.

### 3. Household operations workflow

1. Mealie and Grocy tools support plan + pantry reconciliation.
2. Wellness tools combine Oura/Apple Health/wger context.
3. Chief-of-staff and household personas route outputs through shared formatting skills.

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
