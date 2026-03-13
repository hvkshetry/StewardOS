---
name: quarterly-tax
description: Build an exact 2025/2026 US+MA quarterly-tax plan using the reduced household-tax exact tool surface.
user-invocable: true
---

# /quarterly-tax — Exact Quarterly Tax

Use cross-server baselines and the exact household-tax tools to produce a safe-harbor payment plan. This skill is fail-closed: if the facts are outside the supported 2025/2026 `US` + `MA` individual/fiduciary scope, stop and explain what exact facts are missing or unsupported.

## MCP Tool Map

- Cash-basis income/spend: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Portfolio cashflow context: `ghostfolio.portfolio(operation="dividends", range="1y")`, `ghostfolio.portfolio(operation="summary")`
- Liability and liquidity context: `finance-graph.get_liability_summary`, `finance-graph.list_liabilities`
- Evidence documents: `paperless.search_documents`, `paperless.get_document`
- Exact tax engine:
  - `household-tax.assess_exact_support`
  - `household-tax.ingest_return_facts`
  - `household-tax.compute_individual_return_exact`
  - `household-tax.plan_individual_safe_harbor`
  - `household-tax.compare_individual_payment_strategies`
  - `household-tax.compute_fiduciary_return_exact`
  - `household-tax.plan_fiduciary_safe_harbor`
  - `household-tax.compare_trust_distribution_strategies`

## Canonical Facts Contract

For individual payment planning, build canonical facts with:
- `tax_year` (2025 or 2026)
- `jurisdictions=["US","MA"]`
- `residence_state="MA"`
- `filing_status`
- supported income facts only: `wages`, `taxable_interest`, `ordinary_dividends`, `qualified_dividends`, `short_term_capital_gains`, `long_term_capital_gains`
- `above_line_deductions`
- optional `itemized_deductions` (structured object with `state_local_income_taxes`, `real_estate_taxes`, `mortgage_interest`, `charitable_cash`, `charitable_noncash`, `medical_expenses`, `casualty_loss`, `other`; cannot combine with `annualized_periods`)
- optional `dependents_under_17` and `dependents_under_18` (for child tax credit)
- `withholding_events[]` and `estimated_payments[]`, each with `payment_date`, `amount`, and `jurisdiction` (`US` or `MA`)
- optional `prior_year` facts: `total_tax`, `adjusted_gross_income`, `massachusetts_total_tax`, `full_year_return`, `filed`

For fiduciary planning, use the fiduciary fields instead:
- `fiduciary_kind`
- supported income facts only
- `deductions`
- optional `exemption_amount`
- `capital_gains_in_dni`
- optional `massachusetts` taxable bases when the MA base cannot be derived directly from the supported raw facts

Do not pass unsupported items such as self-employment income, generic other ordinary income, QBI, foreign tax credits, multi-state allocations, or heuristic tax totals.

## Steps

1. Build the YTD baseline from Actual, Ghostfolio, and source documents.
2. Normalize the facts to the exact canonical contract.
3. Call `household-tax.assess_exact_support(entity_type, facts)` first.
4. If unsupported: stop, list the unsupported fields/facts, and do not produce a payment recommendation.
5. If supported and useful for auditability, persist the facts with `household-tax.ingest_return_facts`.
6. For households:
   - call `household-tax.compute_individual_return_exact`
   - call `household-tax.compare_individual_payment_strategies`
   - call `household-tax.plan_individual_safe_harbor`
7. For trusts/estates:
   - call `household-tax.compute_fiduciary_return_exact`
   - call `household-tax.plan_fiduciary_safe_harbor`
   - if distribution timing/amount matters, call `household-tax.compare_trust_distribution_strategies`

## Output Contract

Always include:
- `as_of`
- exact support status
- canonical facts summary
- projected federal + Massachusetts tax
- recommended safe-harbor strategy
- jurisdiction-specific actions with due dates or withholding deadlines
- provenance and unresolved data gaps

Never claim an exact plan when `assess_exact_support.supported` is `false`.
