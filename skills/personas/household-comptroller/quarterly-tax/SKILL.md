---
name: quarterly-tax
description: Calculate quarterly estimated-tax payments with v2 scenario tools and generate an actionable installment plan.
user-invocable: true
---

# /quarterly-tax — Quarterly Estimated Tax

Use cross-server baselines and `household-tax` v2 scenario tools to produce a payment plan with clear assumptions and penalties tradeoffs.

## MCP Tool Map

- Cash-basis income/spend: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Portfolio cashflow context: `ghostfolio.portfolio(operation="dividends", range="1y")`, `ghostfolio.portfolio(operation="summary")`
- Liability and liquidity context: `finance-graph.get_liability_summary`, `finance-graph.list_liabilities`
- Evidence documents: `paperless.search_documents`, `paperless.get_document`
- Tax planning engine (v2): `household-tax.evaluate_scenario`, `household-tax.compare_scenarios`, `household-tax.generate_estimated_payments_plan`, `household-tax.explain_recommendation`

## Steps

1. Build YTD baseline from Actual + Ghostfolio and reconcile unusual jumps against Paperless tax documents.
2. Evaluate both estimated-tax execution scenarios:
- `estimated_tax_method_equal_vs_annualized_installments`
- `withholding_vs_quarterly_payments_for_penalty_control`
3. Compare scenario outputs with objective `min_total_economic_cost` unless the user specifies otherwise.
4. Retrieve the recommended plan via `generate_estimated_payments_plan(plan_id)`.
5. Return due dates, installment amounts, penalty risk, and alternative deltas.

## Output Contract

Always include:
- `as_of` timestamp
- objective and horizon
- selected scenario + recommended strategy
- installment schedule (Q1-Q4)
- key deltas vs next-best alternative
- provenance and unresolved data gaps
