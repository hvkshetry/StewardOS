---
name: returns-analysis
description: Build IRR and MOIC sensitivity ranges for private investments with financing and exit assumptions.
user-invocable: false
---

# Returns Analysis

Estimate investment outcomes for illiquid holdings under multiple scenarios.

## MCP Tool Map

- Public comp valuation anchors: `sec-edgar.sec_edgar_financial`, `sec-edgar.sec_edgar_company`
- Macro/rates assumptions: `market-intel-direct.get_market_snapshot`, `market-intel-direct.get_fred_series`
- Tax scenario overlay: `household-tax.compare_scenarios`

## Workflow

### Step 1: Inputs

- Entry equity, debt terms, current ownership, and expected hold period.
- Revenue and EBITDA trajectory assumptions.
- Exit multiple assumptions and downside/upside bands.

### Step 2: Scenario Grid

- Build base, downside, upside cases.
- Vary growth, margin, leverage paydown, and exit multiple.

### Step 3: Returns Computation

- Compute gross MOIC and IRR by scenario.
- Compute net-of-tax range using household tax scenarios.

### Step 4: Output

- Scenario table with IRR/MOIC ranges.
- Key sensitivities ranked by impact.
- Recommended assumptions to monitor monthly/quarterly.
