---
name: financial-planning
description: Build or update a comprehensive household financial plan using integrated net-worth, cashflow, and the reduced exact household-tax surface where supported.
user-invocable: false
---

# Financial Plan

Use tool-first baselines and the reduced exact household-tax surface where supported. Fail closed when the requested planning case is outside the exact tax engine scope.

## MCP Tool Map

- Cashflow reality: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Investments: `ghostfolio.portfolio(operation="summary")`, `ghostfolio.portfolio(operation="dividends")`
- Net worth and liabilities: `finance-graph.get_net_worth`, `finance-graph.get_liability_summary`, `finance-graph.list_liabilities`
- Tax evidence: `paperless.search_documents`, `paperless.get_document`
- Tax strategy engine: `household-tax.assess_exact_support`, `household-tax.ingest_return_facts`, `household-tax.compute_individual_return_exact`, `household-tax.compute_fiduciary_return_exact`, `household-tax.plan_individual_safe_harbor`, `household-tax.plan_fiduciary_safe_harbor`, `household-tax.compare_trust_distribution_strategies`

## Workflow

1. Build household baseline (income, spend, portfolio, liabilities, net worth) from MCP tools.
2. Ingest and reconcile tax-document evidence from Paperless for key assumptions.
3. Assess whether the requested tax-planning slice is inside the exact 2026 `US` + `MA` support surface.
4. If supported, persist canonical facts with `ingest_return_facts` and run the exact return / safe-harbor / trust-distribution tools that fit the case.
5. If unsupported, stop and explain the missing/unsupported facts rather than synthesizing a broad tax optimization.
6. Present prioritized actions with expected tax and cashflow effects only for supported exact cases.

## Output Contract

Always include:
- baseline snapshot (`as_of`, net worth, cashflow, liabilities)
- exact tax tools run and support status
- recommended exact actions with tradeoffs
- assumptions + sensitivity notes
- provenance and data gaps
