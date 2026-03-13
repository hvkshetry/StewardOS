---
name: dcf-model
description: Discounted cash flow valuation with revenue build-up, margin progression, WACC derivation, and sensitivity analysis.
user-invocable: true
---

# /dcf-model — Discounted Cash Flow Valuation

Produce an intrinsic valuation with explicit assumptions and sensitivity analysis.

## MCP Tool Map

- Company financials: `sec-edgar.sec_edgar_financial`, `sec-edgar.sec_edgar_filing`
- Market/rates context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.get_fred_series`
- Illiquid asset context: `finance-graph.list_assets`, `finance-graph.list_valuation_observations`

## Workflow

### Step 1: Revenue Build-Up

- Establish base revenue from latest filings or operating data.
- Project revenue growth over 5-10 year explicit forecast period.
- Document growth assumptions with supporting evidence.

### Step 2: Margin Progression

- Model operating margin trajectory from current to steady-state.
- Project capex, depreciation, working capital changes.
- Derive unlevered free cash flow for each forecast year.

### Step 3: WACC Derivation

- Risk-free rate from FRED treasury data.
- Equity risk premium and beta estimation.
- Cost of debt and target capital structure.
- Size premium and company-specific risk adjustments where applicable.

### Step 4: Terminal Value

- Calculate terminal value using perpetuity growth method.
- Cross-check with exit multiple method.
- Terminal growth rate must be justified relative to long-term GDP.

### Step 5: Sensitivity Analysis

- Two-way sensitivity on WACC and terminal growth rate.
- Additional sensitivity on revenue growth and margin assumptions.
- Present range of implied values.

### Step 6: Output

- DCF summary with key assumptions table.
- Yearly cash flow projections.
- Sensitivity matrix.
- Implied valuation range with confidence assessment.
- Data gaps and assumption risks.
