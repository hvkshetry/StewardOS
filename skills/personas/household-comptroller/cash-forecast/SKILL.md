---
name: cash-forecast
description: Project household cash position for 30/60/90-day horizons using recurring patterns, scheduled transactions, and known liabilities.
user-invocable: true
---

# /cash-forecast — Cash Position Forecast

Project the household's cash position over 30, 60, and 90-day horizons using recurring patterns, scheduled transactions, and liability obligations.

## MCP Tool Map

- Historical patterns: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Scheduled transactions: `actual-budget.schedule`
- Current balances: `actual-budget.analytics(operation="balance_history")`, `actual-budget.account`
- Liability schedule context: `finance-graph.list_liabilities`, `finance-graph.generate_liability_amortization`, `finance-graph.get_liability_summary`

## Scripts

- `scripts/forecast_builder.py` — driver-based 13-week rolling cash flow projection with scenario modeling; feed it `actual-budget.analytics` historical data and `finance-graph` liability schedule

## Steps

1. Pull current balances and separate liquid cash from credit/other non-liquid accounts.
2. Pull scheduled inflows/outflows and 3-month variable-spend averages.
3. Pull liability obligations from Finance Graph (next payments, amortization rows where needed).
4. Build 30/60/90-day projected balances and identify trough dates.
5. Flag risk conditions (sub-1-month runway, clustered outflows, timing mismatches).

## Output Contract

Always include:
- `as_of` timestamp
- starting liquid cash
- projected balances for 30/60/90 days
- minimum projected balance and date
- assumptions and risk flags
- recommended mitigation actions and provenance
