---
name: dcf-model
description: Produce a discounted cash flow valuation range with explicit assumptions and sensitivity analysis.
user-invocable: false
---

# DCF Valuation

Build a transparent intrinsic valuation for public or private holdings.

## MCP Tool Map

- Historical financial anchors: `sec-edgar.sec_edgar_financial`
- Macro/rate assumptions: `market-intel-direct.get_fred_series`, `market-intel-direct.get_market_snapshot`
- Tax assumptions: `household-tax.compare_tax_scenarios` (for after-tax view)

## Workflow

### Step 1: Forecast Inputs

- Revenue growth path.
- Margin path and capex intensity.
- Working capital assumptions.
- Terminal growth and exit framework.

### Step 2: Discount Rate

- Build WACC assumptions with transparent inputs.
- Use sensitivity bands for risk-free rate and equity risk premium.

### Step 3: Valuation Math

- Forecast free cash flow.
- Discount to present value.
- Add terminal value and compute enterprise/equity value ranges.

### Step 4: Output

- Base case value.
- Sensitivity matrix.
- Assumption register and confidence commentary.
