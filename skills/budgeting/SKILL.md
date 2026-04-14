---
name: budgeting
description: "Personal budgeting and financial planning skill. Use when: (1) Analyzing spending patterns by category or time period, (2) Comparing budget vs actual spending, (3) Calculating savings rates, (4) Forecasting cash flow, (5) Planning tax-aware financial decisions. Tools: actual-mcp for budget/transaction data, ghostfolio-mcp for investment portfolio context."
---

# Personal Budgeting

## Tool Mapping

| Task | MCP Server | Key Tools |
|------|-----------|-----------|
| Transaction history, balances, budgets | actual-budget | `transaction(operation="list")`, `account(operation="list")`, `budget(operation="months"|"month")` |
| Category breakdowns | actual-budget | `analytics(operation="spending_by_category")`, `category(operation="groups_list")` |
| Investment balances and allocation | ghostfolio-mcp | `get_portfolio_summary`, `get_portfolio_positions` |
| Net worth calculation | Both | Actual (cash/debt) + Ghostfolio (investments) |

## Spending Analysis

### Category Breakdown

1. Pull transactions for the target period using `transaction(operation="list")` with date range filters

```
transaction(operation="list", startDate="2025-01-01", endDate="2025-01-31", accountId="checking-main")
```

2. Group by category — report both absolute amounts and percentage of total spend
3. Flag categories that exceed their budget allocation
4. Present results as a ranked table: Category | Budgeted | Actual | Variance | % of Total

### Month-over-Month Trends

1. Pull 3-6 months of transaction data
2. Compute per-category monthly totals
3. Calculate month-over-month change (absolute and percentage)
4. Flag categories with sustained increases (3+ consecutive months of growth)
5. Distinguish between recurring/fixed expenses (rent, insurance, subscriptions) and variable expenses (groceries, dining, entertainment)

### Anomaly Detection

- Flag individual transactions > 2x the category's average transaction size
- Flag categories where current month spend exceeds the trailing 3-month average by > 25%
- Flag new payees not seen in prior months (potential new subscriptions)

## Budget vs Actual Variance Analysis

### Monthly Variance Report

1. Pull budget allocations via `budget(operation="month")` for the target month

```
budget(operation="month", month="2025-01")
```

2. Pull actual spend by category for the same period
3. Compute variance: `actual - budgeted` (negative = under budget, positive = over budget)
4. Present as table: Category | Budget | Actual | Variance | Status (Over/Under/On Track)

### Status Thresholds

| Status | Condition |
|--------|-----------|
| On Track | Actual within +/- 5% of budget |
| Under Budget | Actual < 95% of budget |
| Over Budget | Actual > 105% of budget |
| Critical | Actual > 120% of budget |

### Year-to-Date Tracking

- Accumulate monthly variances to show YTD position per category
- Some categories (e.g., auto maintenance, medical) are lumpy — flag these and compare YTD to annual budget rather than monthly

## Savings Rate Calculation

### Formula

```
Gross Savings Rate = (Total Income - Total Expenses) / Total Income
Net Savings Rate   = (Total Income - Total Expenses - Taxes) / (Total Income - Taxes)
```

### Procedure

1. Pull all income transactions (identify income categories/accounts in Actual)
2. Pull all expense transactions
3. Exclude internal transfers (account-to-account moves) — these are not income or expenses
4. Calculate both gross and net rates
5. Track monthly trend and rolling 3-month average

### Investment Contribution Context

- Use ghostfolio-mcp to pull recent contributions to investment accounts

```
get_portfolio_summary()
get_portfolio_positions()
```

- Include these in the savings rate numerator if they are not already captured as "transfers" in Actual
- Report: Savings Rate (cash) vs Savings Rate (including investments)

## Cash Flow Forecasting

### Short-Term (Next 30-60 Days)

1. Start with current account balances from `account(operation="list")`

```
account(operation="list")
```

2. Identify recurring income (salary dates, rental income, dividends)
3. Identify recurring expenses (rent/mortgage, subscriptions, loan payments, insurance)
4. Subtract known upcoming one-time expenses (if any flagged by user)
5. Project daily balance and flag dates where balance drops below a user-defined threshold

### Procedure

1. Analyze 3-6 months of transaction history to identify recurring patterns
2. Categorize each recurring item: weekly, biweekly, monthly, quarterly, annual
3. Build a forward calendar of expected inflows and outflows
4. Present as a week-by-week projection table: Week | Expected In | Expected Out | Projected Balance

### Seasonal Adjustments

- Flag categories with known seasonal variation (utilities, holiday spending, insurance renewals)
- Use same-month-prior-year data when available for seasonal categories

## Tax-Aware Financial Planning

Tax-aware budgeting integrates transaction tagging, quarterly estimated payments, Schedule C deductions, and capital gains tracking across actual-budget, household-tax-mcp, and ghostfolio-mcp. See [references/TAX_PLANNING.md](references/TAX_PLANNING.md) for detailed tax-aware planning workflows.

## Report Formats

### Monthly Financial Summary

Present in this order:
1. **Income**: Total income, sources breakdown
2. **Expenses**: Total expenses, top 5 categories, budget variance highlights
3. **Savings**: Savings rate (gross and net), trend vs prior month
4. **Net Worth**: Cash + investments - debt, change from prior month
5. **Alerts**: Over-budget categories, anomalous transactions, upcoming large expenses

### When Asked "How am I doing financially?"

1. Current month savings rate vs 3-month average
2. Top 3 over-budget categories with specific amounts
3. Net worth trend (up/down/flat vs prior month)
4. Cash flow health: days of runway at current spend rate
5. One specific, actionable recommendation

## Common Pitfalls

1. **Double-counting transfers** — Exclude account-to-account transfers from income/expense totals
2. **Credit card timing** — Match expenses to transaction date, not payment date
3. **Reimbursements** — Identify and net out reimbursed expenses (or track separately)
4. **Split transactions** — Some transactions span multiple categories; handle splits properly
5. **Investment contributions vs returns** — Contributions are savings; returns are not income for budgeting purposes
