---
name: rebalance
description: Analyze portfolio allocation drift and generate rebalancing trade recommendations across accounts. Considers tax implications, transaction costs, and wash sale rules.
user-invocable: false
---

# Portfolio Rebalance

## MCP Tool Map

- Current holdings and wrappers: `portfolio-analytics.get_condensed_portfolio_state`, `portfolio-analytics.validate_account_taxonomy`
- Drift engine: `portfolio-analytics.analyze_allocation_drift`
- Tax overlay: `portfolio-analytics.find_tax_loss_harvesting_candidates`, `household-tax.compare_scenarios`
- Risk gate: `portfolio-analytics.analyze_portfolio_risk`

## Workflow

### Step 1: Current State (Ghostfolio Source)

- Use `portfolio-analytics.get_condensed_portfolio_state` for scoped holdings and weights
- Validate scope with `portfolio-analytics.validate_account_taxonomy`
- Confirm account wrappers (taxable vs tax-deferred vs tax-exempt)

### Step 2: Drift Analysis

- Use `portfolio-analytics.analyze_allocation_drift` with IPS targets
- Flag symbols exceeding rebalancing bands (typically +/-3% to +/-5%)

### Step 3a: ES-Driven De-Risking (when risk.status == "critical")

When `risk.status == "critical"` or `illiquid_overlay.adjusted_es_975_1d > 0.025`:

1. **Estimate required reduction**:
   `trim_notional = min(portfolio_value × (1 - ES_limit / ES_current), total_liquid_value)`

2. **Get decomposition**: Run `analyze_portfolio_risk(include_decomposition=true)`.
   For wrapper-accurate component VaR: run risk separately for taxable and tax-deferred
   scopes using `scope_wrapper` parameter, so component_var reflects each wrapper's
   contribution correctly.

3. **Cross-reference** `risk_decomposition.component_var_975` with
   `find_tax_loss_harvesting_candidates` output.

4. **Rank sells by tier**:
   - Tier 1: TLH-eligible losers in taxable accounts with high component VaR (tax benefit + risk reduction)
   - Tier 2: High component VaR positions in tax-deferred accounts (risk reduction, no tax event)
   - Tier 3: High component VaR positions in taxable accounts with gains (risk reduction, tax cost)

5. **Present unified trade list**: symbol, account, action, notional, estimated_tax_impact, component_var_pct

6. **Verify**: re-run `analyze_portfolio_risk` with proposed post-trade weights → confirm ES < 2.5%

### Step 3: Trade Recommendations

Generate trades to return toward target:

- Prioritize tax-advantaged wrappers first (IRA/401k/Roth)
- Use taxable sales only when drift is material after tax
- Pair rebalancing with TLH where appropriate
- For major taxable realizations, run a tax scenario comparison before finalizing.

### Step 4: Tax Overlay

- Use `portfolio-analytics.find_tax_loss_harvesting_candidates` for taxable wrappers
- Avoid wash sale conflicts (30-day window)
- Estimate tax drag from realized gains before final trade list

### Step 5: Risk Confirmation

- Run `portfolio-analytics.analyze_portfolio_risk` pre/post proposal
- Enforce binding ES <= 2.5% limit

### Step 6: Output

- Drift table (current vs target)
- Proposed buy/sell notional by symbol/account scope
- Tax impact summary
- ES impact summary
