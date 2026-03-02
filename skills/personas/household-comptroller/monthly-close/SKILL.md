---
name: monthly-close
description: Run month-end close — reconcile Actual Budget, generate P&L/BS/CFS, and record financial statements in finance-graph.
user-invocable: true
---

# /monthly-close — Month-End Close

Reconcile accounts, generate the three core financial statements (P&L, Balance Sheet, Cash Flow Statement), and record them in finance-graph.

## MCP Tool Map

- Transaction and account data: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`, `actual-budget.analytics(operation="balance_history")`, `actual-budget.account`, `actual-budget.transaction`
- Portfolio snapshot (read-only): `ghostfolio.portfolio(operation="summary")`
- Financial statement recording: `finance-graph.record_pl_fact`, `finance-graph.record_cfs_fact`, `finance-graph.record_bs_fact`
- Liability context: `finance-graph.get_liabilities`
- Historical comparison: `finance-graph.query_financial_facts`

## Steps

### 1. Determine Close Period

- Identify the month being closed (default: prior completed month)
- Pull prior month's statements from `finance-graph.query_financial_facts` for comparison

### 2. Reconcile Actual Budget

- Pull `actual-budget.analytics(operation="monthly_summary")` for the close month
- Pull `actual-budget.analytics(operation="balance_history")` for all accounts
- Verify account balances tie to expected values
- Flag any uncleared or unreconciled transactions for review

### 3. Generate Profit & Loss Statement

Build the P&L from Actual Budget data:

```
## P&L — [Month Year]

### Income
| Category | This Month | Prior Month | YTD |
|----------|-----------|-------------|-----|

### Expenses
| Category | This Month | Budget | Variance | YTD |
|----------|-----------|--------|----------|-----|

### Summary
| | This Month | Prior Month | YTD |
|---|-----------|-------------|-----|
| Total Income | | | |
| Total Expenses | | | |
| Net Income | | | |
| Savings Rate | | | |
```

Record each line item via `finance-graph.record_pl_fact`.

### 4. Generate Balance Sheet

Combine Actual Budget (cash + debt accounts) with Ghostfolio (investments) and finance-graph (illiquid assets + liabilities):

```
## Balance Sheet — [Month-End Date]

### Assets
| Category | Amount |
|----------|--------|
| Cash & checking (Actual) | |
| Savings (Actual) | |
| Investment accounts (Ghostfolio) | |
| Illiquid assets (finance-graph) | |
| Total Assets | |

### Liabilities
| Category | Amount |
|----------|--------|
| Credit cards (Actual) | |
| Mortgage (finance-graph) | |
| Other liabilities (finance-graph) | |
| Total Liabilities | |

| **Net Worth** | |
```

Record via `finance-graph.record_bs_fact`.

### 5. Generate Cash Flow Statement

Derive CFS from Actual Budget transaction flows:

```
## Cash Flow Statement — [Month Year]

### Operating Activities
| Item | Amount |
|------|--------|
| Net income | |
| Adjustments (non-cash) | |
| Net cash from operations | |

### Investing Activities
| Item | Amount |
|------|--------|
| Investment contributions | |
| Investment withdrawals | |
| Net cash from investing | |

### Financing Activities
| Item | Amount |
|------|--------|
| Debt payments (principal) | |
| New borrowing | |
| Net cash from financing | |

| **Net Change in Cash** | |
| **Ending Cash Position** | |
```

Record via `finance-graph.record_cfs_fact`.

### 6. Month-over-Month Comparison

- Compare P&L, BS, and CFS to prior month and same month prior year (if available)
- Flag significant variances (>10% or >$500 absolute change)

### 7. Output

Produce a consolidated close package:
- P&L with budget variance
- Balance sheet with prior-month comparison
- Cash flow statement
- Reconciliation notes (any flagged items)
- Key metrics: savings rate, debt-to-asset ratio, cash runway
