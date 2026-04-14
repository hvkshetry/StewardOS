# Tax-Aware Financial Planning

## Tax-Relevant Transaction Tagging

Ensure these categories are properly tracked in Actual for tax time:
- Business expenses (Schedule C — use `categorize_schedule_c_deductions` from household-tax-mcp)
- Health insurance premiums (self-employed deduction)
- Retirement contributions (SEP-IRA, Solo 401(k))
- Charitable donations (Schedule A itemized deductions)
- Home office expenses (simplified or actual method)
- Professional development and education
- Travel and business meals (50% deductible)

## Quarterly Estimated Tax Payments (1040-ES)

1. Pull YTD income from Actual (self-employment, W-2, investment income)
2. Pull capital gains/dividends from ghostfolio-mcp
3. Normalize facts to the reduced exact `household-tax` contract
4. Use `assess_exact_support` before any tax recommendation
5. If supported, use `compute_individual_return_exact`, `compare_individual_payment_strategies`, and `plan_individual_safe_harbor`
6. If unsupported, stop and report the gap rather than approximating

## Self-Employment Tax (Schedule SE)

Self-employment income is outside the reduced exact household-tax scope. For these cases:
- Deductible half of SE tax (reduces AGI)
- Do not use `household-tax` as an exact calculator; surface the unsupported scope explicitly

## Schedule C Deduction Categorization

Use `categorize_schedule_c_deductions` to map Actual Budget expense categories to Schedule C lines. Review unmapped categories quarterly to ensure all deductions are captured.

## Exact Tax Support

`household-tax` no longer exposes generic scenario comparison tools. Use the
exact quarterly-tax/safe-harbor surface only when the case is inside the
supported 2026 `US` + `MA` scope; otherwise flag that exact household-tax
support is unavailable for the requested budgeting decision.

## Integration with Ghostfolio

- Pull capital gains data from ghostfolio-mcp for tax planning
- Short-term vs long-term classification based on holding period (1 year for equities)
- Coordinate with investing-workspace tax servers for wash sale and TLH analysis
