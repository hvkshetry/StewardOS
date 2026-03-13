# Skill Contribution Guide

## What skills are

Skills are markdown files that encode repeatable workflows for a specific persona. They define exactly which MCP tools to call, in what order, with what parameters, and what the output should look like. When a persona executes a skill, it follows the skill's workflow instead of improvising — this is what makes outputs consistent across runs.

Skills live in `skills/personas/<persona>/<skill-name>/SKILL.md`.

## Who should contribute

If you manage your own portfolio, run your own household budget, track your own health, or handle your own estate planning — you already have workflows that produce reliable results. A skill contribution encodes one of those workflows so it runs the same way every time.

You do not need to run the full StewardOS stack to contribute a skill. Skills are markdown files — you can write and submit them through the GitHub web editor.

## Anatomy of a skill

Every skill follows the same structure: YAML frontmatter for metadata, then a markdown document with tool map, workflow steps, and output contract.

```markdown
---
name: budget-review
description: >
  Monthly budget variance analysis comparing Actual Budget transactions
  against expected spending by category. Use when the user asks for budget
  review, spending analysis, or wants to understand where money went.
user-invocable: true
---

# /budget-review — Monthly Budget Variance Analysis

Analyze spending patterns against budget targets and flag anomalies.

## MCP Tool Map

- Transaction data: `actual-budget.analytics(operation="spending_by_category")`
- Monthly summary: `actual-budget.analytics(operation="monthly_summary")`
- Balance context: `actual-budget.analytics(operation="balance_history")`
- Net worth context: `finance-graph.get_net_worth`

## Execution Workflow

### Step 1: Pull Current Month Data

- Run `actual-budget.analytics(operation="monthly_summary")` for the target month.
- Run `actual-budget.analytics(operation="spending_by_category")` for category breakdown.

### Step 2: Compare Against Targets

- Compare each category against expected monthly budget.
- Flag any category exceeding budget by more than 15%.
- Identify categories significantly under budget (potential timing issues vs real savings).

### Step 3: Identify Anomalies

- Look for unusual transactions (large one-time expenses, duplicate charges).
- Compare against prior 3-month average for each category.
- Flag new categories that appeared this month.

### Step 4: Produce Output

## Output Contract

Always include:
- Period analyzed and as-of date
- Total income vs total expense vs net
- Top 5 categories by spend with budget comparison
- Anomaly list with explanations
- Variance summary (over-budget / under-budget / on-track counts)
- Provenance for each data source
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Kebab-case identifier matching the directory name |
| `description` | yes | When to use this skill — include trigger phrases so the persona knows when to activate it |
| `user-invocable` | yes | `true` if the user can trigger it directly via `/command`, `false` if it's only called by other skills or backend workflows |

## Expected output shape

Every skill should define an output contract — the structure of what it produces. This is how reviewers and other contributors know what to expect.

Good output contracts specify:
- **Required sections** (what must always be present)
- **Data provenance** (which tool produced each figure)
- **Format** (markdown tables, bullet lists, structured sections)
- **Conditional sections** (included only when relevant — e.g., "Anomaly list" only if anomalies found)

## Common tool patterns by persona

These are the most frequently used MCP tools for each persona. Reference these when designing your skill's tool map.

### Portfolio Manager

| Tool | Server | What It Returns |
|------|--------|----------------|
| `get_condensed_portfolio_state` | portfolio-analytics | Holdings, weights, unrealized P&L by scope |
| `analyze_portfolio_risk` | portfolio-analytics | ES, VaR, volatility, drawdown, Student-t fit, vol regime |
| `analyze_allocation_drift` | portfolio-analytics | Current vs target weights with rebalance notionals |
| `find_tax_loss_harvesting_candidates` | portfolio-analytics | Unrealized losses with replacement suggestions |
| `get_market_snapshot` | market-intel-direct | Current indices, rates, commodities |
| `search_market_news` | market-intel-direct | Recent news articles by query |
| `get_macro_context_panel` | market-intel-direct | Multi-series FRED data for regime analysis |
| `sec_edgar_filing` | sec-edgar | Recent SEC filings by company |
| `sec_edgar_insider` | sec-edgar | Insider transaction summary |
| `discover_work_items` | plane-pm | Work items in investment-office workspace |
| `create_work_item` | plane-pm | Create task or delegate to Research Analyst |

### Research Analyst

| Tool | Server | What It Returns |
|------|--------|----------------|
| `get_market_snapshot` | market-intel-direct | Current indices, rates, commodities |
| `search_market_news` | market-intel-direct | Recent news articles by query |
| `get_macro_context_panel` | market-intel-direct | Multi-series FRED data for regime analysis |
| `get_symbol_history` | market-intel-direct | Historical price data for analysis |
| `sec_edgar_filing` | sec-edgar | Recent SEC filings by company |
| `sec_edgar_financial` | sec-edgar | Financial statement data via XBRL |
| `sec_edgar_insider` | sec-edgar | Insider transaction summary |

### Household Comptroller

| Tool | Server | What It Returns |
|------|--------|----------------|
| `analytics(operation="monthly_summary")` | actual | Monthly income/expense/net summary |
| `analytics(operation="spending_by_category")` | actual | Category-level spending breakdown |
| `upsert_financial_statement_period` | finance-graph | Create/update reporting period |
| `upsert_statement_line_items` | finance-graph | Persist P&L/BS/CFS line items |
| `compute_individual_return_exact` | household-tax | Exact 2025/2026 individual tax return |
| `plan_individual_safe_harbor` | household-tax | Safe-harbor payment planning |
| `compare_individual_payment_strategies` | household-tax | Payment strategy comparison |

### Estate Counsel

| Tool | Server | What It Returns |
|------|--------|----------------|
| `get_ownership_graph` | estate-planning | Recursive ownership hierarchy |
| `get_net_worth` | estate-planning | Net worth by person or jurisdiction |
| `get_upcoming_dates` | estate-planning | Critical dates due within N days |
| `upsert_entity` | estate-planning | Create/update trust, LLC, corp |
| `link_document` | estate-planning | Connect Paperless document to estate record |

### Household Director

| Tool | Server | What It Returns |
|------|--------|----------------|
| `get_stock_overview` | grocy | Current pantry inventory |
| `get_missing_products` | grocy | Below-minimum-stock items |
| `get_shopping_list` | grocy | Current shopping list |
| `get_learner_profile` | family-edu | Child development summary |
| `create_weekly_activity_plan` | family-edu | Weekly activity schedule |

### Wellness Advisor

| Tool | Server | What It Returns |
|------|--------|----------------|
| `get_workout_log` | wger | Recent exercise entries |
| `get_nutrition_values` | wger | Macro calculations for nutrition plan |
| `get_body_weight` | wger | Weight history over time |
| `get_wellness_recommendations` | health-graph | Genome-aware wellness recommendations |
| `get_pgx_context` | health-graph | Pharmacogenomics context for a subject |
| `get_polygenic_context` | health-graph | Polygenic risk score context |
| `query_variant_assertions` | health-graph | Clinical variant assertions |

### Insurance Advisor

| Tool | Server | What It Returns |
|------|--------|----------------|
| `search` | paperless | Policy documents, declarations pages, EOBs |
| `get_net_worth` | finance-graph | Asset/liability context for coverage adequacy |
| `get_ownership_graph` | estate-planning | Trust/entity structure for named-insured alignment |
| `analytics(operation="spending_by_category")` | actual | Premium payment tracking, insurance budget lines |

## Testing your skill

Before submitting, verify your skill works:

1. **Tool references resolve**: every tool in your MCP Tool Map exists on the listed server. Check [`docs/architecture/mcp-servers/README.md`](../architecture/mcp-servers/README.md) for the tool inventory.
2. **Workflow steps are ordered correctly**: each step's inputs are available from prior steps or initial context.
3. **Output contract is complete**: run through the workflow mentally and verify the output contract covers everything the workflow produces.
4. **Boundaries are respected**: the skill only uses tools available to its persona (check the persona's `AGENTS.md` for server access rules).

If you have the stack running locally, execute the skill via the persona and verify:
- All tool calls succeed
- Output matches the defined contract
- No data is fabricated (all figures trace to tool outputs)

## No-local-setup contribution path

You can contribute skills without running StewardOS locally:

1. Browse existing skills in `skills/personas/<persona>/` on GitHub to understand the pattern
2. Create your skill directory and `SKILL.md` using the GitHub web editor
3. Use the PR checklist below to verify quality

### PR checklist for skill contributions

- [ ] `SKILL.md` has valid YAML frontmatter (`name`, `description`, `user-invocable`)
- [ ] `name` in frontmatter matches the directory name
- [ ] `description` includes trigger phrases for when the skill should activate
- [ ] MCP Tool Map references only tools available to the target persona
- [ ] Execution workflow steps are ordered (no step depends on data from a later step)
- [ ] Output contract defines required sections and provenance expectations
- [ ] No personal identifiers, email addresses, account IDs, or domain names
- [ ] No hardcoded secrets, API keys, or environment-specific values
- [ ] Skill respects persona boundaries (no cross-persona tool usage)
