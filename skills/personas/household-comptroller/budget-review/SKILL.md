---
name: budget-review
description: Analyze current month budget variance, spending trends, anomalies, and savings rate.
user-invocable: true
---

# /budget-review — Budget Variance Analysis

Analyze the current month's budget performance with trend context, anomaly detection, and savings rate tracking.

## MCP Tool Map

- Monthly aggregates: `actual-budget.analytics(operation="monthly_summary")`
- Category breakdown: `actual-budget.analytics(operation="spending_by_category")`
- Budget targets: `actual-budget.budget`
- Transaction detail: `actual-budget.transaction`
- Account balances: `actual-budget.analytics(operation="balance_history")`

## Steps

### 1. Pull Current Month Data

- `actual-budget.analytics(operation="monthly_summary")` for current and prior 3 months
- `actual-budget.analytics(operation="spending_by_category")` for current month
- `actual-budget.budget` for current month budget targets by category

### 2. Variance Analysis

Compare actual spending to budget by category:

```
## Budget Variance — [Month Year]

| Category | Budget | Actual | Variance | % | Status |
|----------|--------|--------|----------|---|--------|
| | | | | | Over/Under/On Track |

### Summary
| | Amount |
|---|--------|
| Total Budgeted | |
| Total Spent | |
| Net Variance | |
```

Flag categories with:
- Overspend >10% or >$100
- Underspend >25% (potential missed entries or timing)

### 3. Trend Analysis

Compare current month to rolling 3-month average:

```
### Spending Trends
| Category | 3-Mo Avg | This Month | Delta | Trend |
|----------|----------|-----------|-------|-------|
| | | | | Rising/Falling/Stable |
```

Flag categories with sustained rising trends (3+ consecutive months of increase).

### 4. Anomaly Detection

Scan for unusual patterns:
- Single transactions >2x the category's monthly average
- New payees not seen in prior 3 months with amounts >$100
- Categories with zero spend that normally have activity
- Duplicate or near-duplicate transactions (same payee, same amount, same day)

### 5. Savings Rate Calculation

```
### Savings Rate
| Metric | Amount |
|--------|--------|
| Total Income | |
| Total Expenses | |
| Net Savings | |
| Savings Rate | X% |
| 3-Month Avg Savings Rate | X% |
| YTD Savings Rate | X% |
```

### 6. Output

```
## Budget Review — [Month Year]

### Key Findings
- [2-3 headline observations]

### Variance Summary
[Table from Step 2]

### Trend Highlights
[Notable trends from Step 3]

### Anomalies
[Flagged items from Step 4]

### Savings Rate
[Metrics from Step 5]

### Action Items
- [Specific budget adjustments or follow-ups needed]
```
