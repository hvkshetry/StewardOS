---
name: net-worth-report
description: Generate a consolidated household net worth report from Actual, Ghostfolio, and Finance Graph with source-level provenance.
user-invocable: true
---

# /net-worth — Consolidated Net Worth Report

Produce an assets/liabilities snapshot and change analysis using canonical tool sources.

## MCP Tool Map

- Cash accounts and card balances: `actual-budget.account`, `actual-budget.analytics(operation="balance_history")`
- Portfolio value (read-only): `ghostfolio.portfolio(operation="summary")`
- Household net worth and debt: `finance-graph.get_net_worth`, `finance-graph.list_assets`, `finance-graph.list_liabilities`, `finance-graph.get_liability_summary`

## Steps

1. Pull all cash and liability-style accounts from Actual and classify asset vs liability balances.
2. Pull investment totals from Ghostfolio.
3. Pull non-portfolio assets and liabilities from Finance Graph.
4. Consolidate into total assets, total liabilities, and net worth.
5. Compare against prior period via `actual-budget.analytics(operation="balance_history")` plus latest Finance Graph snapshots.

## Output Contract

Always include:
- `as_of` timestamp
- asset buckets and totals
- liability buckets and totals
- net worth and period-over-period change
- composition ratios (liquid vs invested vs illiquid; debt-to-asset)
- provenance + stale/missing-data flags
