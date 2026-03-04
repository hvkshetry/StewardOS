---
name: monthly-close
description: Run month-end close using Actual + Ghostfolio + Finance Graph, then persist P&L/CFS/BS line items in Finance Graph.
user-invocable: true
---

# /monthly-close — Month-End Close

Reconcile month-end data, assemble P&L/BS/CFS, and write statement facts to Finance Graph.

## MCP Tool Map

- Transaction and balances: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`, `actual-budget.analytics(operation="balance_history")`, `actual-budget.account`
- Portfolio snapshot: `ghostfolio.portfolio(operation="summary")`
- Statement persistence: `finance-graph.upsert_financial_statement_period`, `finance-graph.upsert_statement_line_items`
- Balance sheet context: `finance-graph.get_net_worth`, `finance-graph.list_liabilities`

## Steps

1. Determine close period and pull Actual monthly summary + category breakdown.
2. Build draft P&L, BS, and CFS from Actual + Ghostfolio + Finance Graph context.
3. Create/update reporting period via `upsert_financial_statement_period`.
4. Persist each statement with `upsert_statement_line_items`:
- `statement_type="income_statement"`
- `statement_type="cash_flow_statement"`
- `statement_type="balance_sheet"`
5. Return close package with reconciliation exceptions and key ratios.

## Output Contract

Always include:
- period closed and `as_of`
- P&L summary (income, expense, net income, savings rate)
- BS summary (assets, liabilities, net worth)
- CFS summary (operating/investing/financing/net change)
- reconciliation issues and follow-ups
- provenance for each figure set
