---
description: Analyze portfolio factor exposures and hedging ideas using Fama-French factors
allowed-tools: mcp__portfolio-state-server__get_portfolio_state, mcp__openbb-curated__famafrench_factor_loadings, mcp__risk-server__analyze_portfolio_risk, Write
status: planned
prerequisites:
  - "Expose Fama-French router through openbb-curated (use OpenBB famafrench provider)"
  - "Add factor exposure output in risk-server (ES-by-factor decomposition)"
  - "Implement factor regression in portfolio-optimization-server"
argument-hint: <analysis_type> (e.g., "exposures", "attribution", "hedging")
---

Analyze portfolio factor exposures using Fama-French multi-factor model. This workflow decomposes returns and risk into systematic factors for better understanding of portfolio tilts and hedge construction.

## Prerequisites

**NOT YET IMPLEMENTED - FUTURE ENHANCEMENT**

Required integrations:
1. OpenBB Fama-French provider exposed via `mcp__openbb-curated__famafrench_factor_loadings`
2. Risk server extended with `factor_exposure` and `es_by_factor` outputs
3. Portfolio optimization server with factor-based optimization methods

## Workflow Steps (When Implemented)

1. **Get Portfolio Holdings**
   - Retrieve current positions with `mcp__portfolio-state-server__get_portfolio_state`
   - Extract tickers, weights, and historical returns

2. **Load Factor Data**
   - Get Fama-French factor returns with `mcp__openbb-curated__famafrench_factor_loadings`
   - Models supported:
     - **FF3**: Market, Size (SMB), Value (HML)
     - **FF5**: FF3 + Profitability (RMW), Investment (CMA)
     - **Momentum**: Fama-French + Momentum (UMD)
   - Use 3-year lookback for regression

3. **Calculate Factor Exposures**
   - Run factor regression for each position
   - Portfolio-level factor loadings = weighted sum of position loadings
   - Extract:
     - Market beta
     - Size tilt (SMB exposure)
     - Value tilt (HML exposure)
     - Profitability tilt (RMW exposure)
     - Investment tilt (CMA exposure)
     - Momentum exposure (UMD)
   - Calculate R-squared and alpha
   - Create `factor_exposures.json`

4. **Risk Decomposition by Factor**
   - Extend risk analysis to decompose ES by factor
   - Use `mcp__risk-server__analyze_portfolio_risk` with factor breakdown
   - Calculate:
     - Contribution of each factor to portfolio variance
     - Factor-specific VaR and ES
     - Correlation between factors
   - Create `factor_risk_decomposition.json`

5. **Attribution Analysis**
   - Decompose portfolio returns into factor contributions
   - Separate systematic (factor) vs idiosyncratic (alpha) returns
   - Calculate:
     - Return attribution by factor
     - Unexplained return (alpha or error)
     - Factor timing contribution
   - Create `factor_attribution.json`

6. **Generate Factor Report**
   - Use `@risk-analyst` agent to synthesize
   - Create `factor_analysis.md` with:
     - **Portfolio Tilts**: Summary of factor exposures vs market
     - **Factor Attribution**: Which factors drove returns
     - **Risk Sources**: Factor contribution to ES
     - **Hedging Ideas**: Suggest factor-neutral overlays if needed
     - **Comparison**: Portfolio factors vs style benchmark (Growth/Value/Blend)

## Agents Used

- `@risk-analyst` - Factor analysis and risk decomposition
- `@portfolio-manager` - Factor-based optimization (if hedging)

## Output Location

Save all artifacts to current session directory.

## Success Criteria

- `factor_exposures.json` with FF3/FF5 loadings
- `factor_risk_decomposition.json` with ES-by-factor
- `factor_attribution.json` with return decomposition
- `factor_analysis.md` with hedging recommendations

## Example Usage (Future)

```
/factor-analysis exposures
```

Analyze current factor tilts (market, size, value, profitability, investment).

```
/factor-analysis hedging
```

Generate factor-neutral hedge recommendations to reduce systematic risk.

## Implementation Notes

- **OpenBB Integration**: Use `openbb.equity.fundamental.metrics` with Fama-French provider
- **Factor Data Source**: Kenneth French Data Library (via OpenBB)
- **Regression Method**: OLS with Newey-West standard errors
- **Lookback Period**: 36 months (3 years) for stable estimates
- **Rebalancing**: Monthly factor data alignment

## Future Enhancements

- Add custom factor models (e.g., quality, low volatility)
- Implement dynamic factor timing strategies
- Add factor-based portfolio optimization constraints
- Integrate with options overlay for factor hedging
