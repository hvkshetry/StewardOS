---
name: portfolio-monitoring
description: Monitor illiquid/private holdings and operating KPIs against plan, with valuation and risk implications.
user-invocable: false
---

# Portfolio Monitoring (Private / Illiquid)

Track performance of non-public holdings and connect results to household portfolio decisions.

## MCP Tool Map

- Illiquid holdings source-of-truth: `finance-graph.list_assets`, `finance-graph.list_valuation_observations`, `finance-graph.upsert_financial_statement_period`, `finance-graph.upsert_statement_line_items`
- Estate-planning boundary: `estate-planning` is for legal/succession ownership records, not valuation or PL/CFS/BS storage
- Household portfolio context: `ghostfolio.account`, `ghostfolio.portfolio`, `portfolio-analytics.get_condensed_portfolio_state`
- Market and macro context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.get_macro_context_panel`
- Public comp disclosure benchmarks: `sec-edgar.sec_edgar_company`, `sec-edgar.sec_edgar_financial`, `sec-edgar.sec_edgar_filing`
- Tax impact context: only use `household-tax.assess_exact_support` for supported exact household-tax cases

## Workflow

### Step 1: Ingest Operating Package

- Collect manual KPI inputs: revenue, EBITDA, cash, debt, capex, working capital, backlog, churn, orders.
- Capture reporting period and budget/plan reference.
- Maintain asset metadata via normalized taxonomy (`asset_class_code`, `asset_subclass_code`) and explicit `jurisdiction_code`/`valuation_currency`.

### Step 2: Variance and Trend Review

- Compute actual vs budget variance.
- Flag material misses and explain operational drivers.
- Separate one-off noise from structural change.

### Step 3: External Benchmarking

- Select public comps and pull recent disclosure metrics.
- Compare growth, margins, leverage, and valuation bands.

### Step 4: Portfolio and Tax Relevance

- Assess how updated private valuation/risk affects total household allocation.
- Report portfolio totals with explicit semantics: `investments_value_ex_cash`, `cash_balance`, `net_worth_total`.
- Summarize likely tax outcomes of hold, partial sale, or recap scenarios.

### Step 5: Monitoring Output

- KPI dashboard.
- Red/amber/green risk flags.
- Required management follow-ups.
- Next-period watch items.
