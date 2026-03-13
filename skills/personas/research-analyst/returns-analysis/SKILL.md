---
name: returns-analysis
description: IRR/MOIC scenario analysis for private investments — entry valuation, hold period, exit assumptions, and sensitivity to key drivers.
user-invocable: true
---

# /returns-analysis — IRR/MOIC Scenario Analysis

Model investor-outcome scenarios for private or illiquid investments.

## MCP Tool Map

- Illiquid asset context: `finance-graph.list_assets`, `finance-graph.list_valuation_observations`, `finance-graph.get_ownership_graph`
- Market/rates context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.get_fred_series`
- Comparable exit context: `sec-edgar.sec_edgar_financial`, `sec-edgar.sec_edgar_filing`

## Workflow

### Step 1: Investment Parameters

- Entry valuation and investment amount.
- Ownership percentage, instrument type, and rights.
- Expected hold period and liquidity constraints.

### Step 2: Base Case Modeling

- Project operating performance over hold period.
- Determine exit valuation using comparable transactions or multiple-based approach.
- Calculate gross IRR and MOIC for the base case.

### Step 3: Scenario Analysis

- **Bull case**: Accelerated growth, multiple expansion, early exit.
- **Base case**: Plan-line performance, stable multiples.
- **Bear case**: Slower growth, margin compression, delayed exit or down-round.
- Calculate IRR and MOIC for each scenario.

### Step 4: Sensitivity Analysis

- Key driver sensitivities: revenue growth, exit multiple, hold period, dilution.
- Identify break-even assumptions for minimum acceptable return threshold.

### Step 5: Output

- Scenario summary table (IRR, MOIC, exit value per scenario).
- Sensitivity matrix on top two drivers.
- Key risks and mitigants.
- Comparison to portfolio return requirements.
- Data gaps and assumption risks.
