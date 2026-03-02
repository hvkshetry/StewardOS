---
name: cash-forecast
description: Project household cash position for 30/60/90-day horizons using recurring patterns, scheduled transactions, and known liabilities.
user-invocable: true
---

# /cash-forecast — Cash Position Forecast

Project the household's cash position over 30, 60, and 90-day horizons based on recurring income/expense patterns, scheduled transactions, and known liabilities.

## MCP Tool Map

- Historical patterns: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Scheduled transactions: `actual-budget.schedule`
- Current balances: `actual-budget.analytics(operation="balance_history")`, `actual-budget.account`
- Liability schedule: `finance-graph.get_liabilities`

## Steps

### 1. Establish Current Position

- Pull current account balances via `actual-budget.account` and `actual-budget.analytics(operation="balance_history")`
- Separate liquid cash (checking, savings) from credit lines and investment accounts
- Note any pending/uncleared transactions that affect available cash

### 2. Map Recurring Inflows

- Pull `actual-budget.schedule` for scheduled income entries
- Cross-reference with `actual-budget.analytics(operation="monthly_summary")` for consistency
- Identify recurring inflows: salary, freelance income, dividends, rental income, transfers

### 3. Map Recurring Outflows

- Pull `actual-budget.schedule` for scheduled expense entries
- Identify recurring outflows: rent/mortgage, utilities, subscriptions, insurance premiums, loan payments
- Pull `finance-graph.get_liabilities` for debt service schedules (principal + interest)
- Cross-reference with 3-month spending averages for variable categories (groceries, gas, dining)

### 4. Identify Known One-Time Items

- Upcoming scheduled transactions not on a recurring cycle
- Known large expenses (tax payments, insurance renewals, tuition)
- Expected one-time income (tax refunds, bonuses)

### 5. Build Forecast

Project cash position at 30, 60, and 90 days:

```
## Cash Forecast — [Date]

### Starting Position
| Account | Balance |
|---------|---------|
| Checking | |
| Savings | |
| Total Liquid Cash | |

### 30-Day Projection ([Date Range])
| Category | Amount |
|----------|--------|
| Expected inflows | |
| Recurring expenses | |
| Scheduled one-time | |
| Variable estimate (3-mo avg) | |
| Net cash flow | |
| **Projected balance** | |

### 60-Day Projection ([Date Range])
[Same structure]

### 90-Day Projection ([Date Range])
[Same structure]

### Cash Runway
- Months of expenses covered by current liquid cash: X.X
- Minimum projected balance: $X on [date]
- Emergency fund target: $X (X months of expenses)
- Emergency fund status: [Adequate / Below Target]
```

### 6. Risk Flags

Flag potential issues:
- Projected balance dropping below 1 month of expenses
- Large outflows concentrating in a single week
- Income timing gaps (e.g., bi-weekly payroll alignment)
- Upcoming liability payments without sufficient scheduled income cover

### 7. Output

- Cash position summary table (current + 30/60/90-day)
- Key assumptions listed (which recurring items, what averages used)
- Risk flags with recommended actions
- Cash runway metric
