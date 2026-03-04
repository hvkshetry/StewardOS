---
name: financial-planning
description: Build or update a comprehensive household financial plan using integrated net-worth, cashflow, and household-tax v2 scenario analysis.
user-invocable: false
---

# Financial Plan

Use tool-first baselines and v2 scenario optimization to produce an actionable multi-year plan.

## MCP Tool Map

- Cashflow reality: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Investments: `ghostfolio.portfolio(operation="summary")`, `ghostfolio.portfolio(operation="dividends")`
- Net worth and liabilities: `finance-graph.get_net_worth`, `finance-graph.get_liability_summary`, `finance-graph.list_liabilities`
- Tax evidence: `paperless.search_documents`, `paperless.get_document`
- Tax strategy engine: `household-tax.upsert_tax_profile`, `household-tax.optimize_strategy`, `household-tax.compare_scenarios`, `household-tax.explain_recommendation`

## Workflow

1. Build household baseline (income, spend, portfolio, liabilities, net worth) from MCP tools.
2. Ingest and reconcile tax-document evidence from Paperless for key assumptions.
3. Persist/update planning profile via `upsert_tax_profile`.
4. Run strategy groups in `household-tax`:
- `comprehensive_household_tax`
- `business_owner_planning`
- `trust_distribution_policy`
5. Compare objective-aligned recommendations (default `max_end_net_worth`, 5-year horizon).
6. Present prioritized actions with expected tax, cashflow, and end-net-worth deltas.

## Output Contract

Always include:
- baseline snapshot (`as_of`, net worth, cashflow, liabilities)
- scenarios run and ranking criteria
- recommended strategy set with tradeoffs
- assumptions + sensitivity notes
- provenance and data gaps
