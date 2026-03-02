---
name: quarterly-tax
description: Calculate quarterly 1040-ES estimated tax payment, verify safe harbor, and generate voucher amounts.
user-invocable: true
---

# /quarterly-tax — Quarterly Estimated Tax

Calculate the next quarterly estimated tax payment (1040-ES) and verify safe harbor compliance.

## MCP Tool Map

- Income and spend context: `actual-budget.analytics(operation="monthly_summary")`, `actual-budget.analytics(operation="spending_by_category")`
- Portfolio cashflow context: `ghostfolio.portfolio(operation="dividends", range="1y")`
- Tax engine: `household-tax.estimate_quarterly_1040es`, `household-tax.compute_schedule_se`, `household-tax.project_safe_harbor`, `household-tax.generate_quarterly_vouchers`
- Business expense mapping: `household-tax.categorize_schedule_c_deductions`

## Steps

### 1. Gather Income Data

- **Actual Budget**: YTD income and expenses by category
- **Ghostfolio**: Realized dividends and portfolio cashflow context

### 2. Calculate Tax Estimate (household-tax)

- `household-tax.estimate_quarterly_1040es` — compute next quarterly payment
  - Input: YTD income, estimated remaining income, filing status, deductions
  - Output: federal + state estimated tax, quarterly payment amount

### 3. Self-Employment Tax

- `household-tax.compute_schedule_se` — Social Security + Medicare tax on SE income

### 4. Safe Harbor Verification

- `household-tax.project_safe_harbor` — verify payments meet safe harbor threshold
  - 110% of prior year tax (if AGI > $150k) or 100% (if AGI <= $150k)
  - 90% of current year tax

### 5. Schedule C Deductions

- `household-tax.categorize_schedule_c_deductions` — map Actual Budget expense categories to Schedule C line items
- Review unmapped categories and deduction impact

### 6. Full-Year Voucher Schedule

- `household-tax.generate_quarterly_vouchers` — all 4 quarterly payment amounts and due dates

### 7. Output

```
## Quarterly Tax Estimate — Q[N] [Year]

### Income Summary (YTD)
| Source | Amount |
|--------|--------|
| Self-employment | $X |
| W-2 wages | $X |
| Capital gains (realized) | $X |
| Dividends + interest | $X |
| Total | $X |

### Tax Calculation
| Item | Amount |
|------|--------|
| Federal income tax | $X |
| Self-employment tax | $X |
| State income tax | $X |
| Total estimated tax | $X |

### Quarterly Payment
- Next payment due: [Date]
- Amount: $X (federal) + $X (state)

### Safe Harbor Status
- Prior year tax x 110%: $X — [Met/Not Met]
- Current year tax x 90%: $X — [Met/Not Met]
- Status: [SAFE / AT RISK]

### Full-Year Schedule
| Quarter | Due Date | Federal | State | Cumulative |
|---------|----------|---------|-------|------------|
```
