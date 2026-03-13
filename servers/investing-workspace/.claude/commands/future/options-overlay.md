---
description: Design options overlay strategy for income generation or downside protection
allowed-tools: mcp__portfolio-state-server__get_portfolio_state, mcp__openbb-curated__derivatives_options_chains, mcp__risk-server__analyze_portfolio_risk, Write
status: planned
prerequisites:
  - "Integrate QuantLib for options pricing (Black-Scholes, binomial, Monte Carlo)"
  - "Add Greeks calculation to derivatives tools"
  - "Implement options position tracking in portfolio-state-server"
  - "Add options risk metrics to risk-server (e.g., gamma exposure, vega risk)"
argument-hint: <strategy_type> (e.g., "covered-call", "protective-put", "collar")
---

Design and analyze options overlay strategies for portfolio enhancement. This workflow helps construct income-generating or protective options strategies on top of existing equity positions.

## Prerequisites

**NOT YET IMPLEMENTED - FUTURE ENHANCEMENT**

Required integrations:
1. QuantLib pricing engine for accurate options valuation
2. Greeks calculation (Delta, Gamma, Vega, Theta, Rho)
3. Options position tracking in portfolio-state-server
4. Options-specific risk metrics in risk-server

## Workflow Steps (When Implemented)

1. **Get Portfolio Holdings**
   - Retrieve equity positions with `mcp__portfolio-state-server__get_portfolio_state`
   - Filter for optionable stocks (>$5, liquid options market)
   - Extract current shares, cost basis, unrealized gains

2. **Retrieve Options Chains**
   - For each eligible position, get options chain with `mcp__openbb-curated__derivatives_options_chains`
   - Focus on:
     - Near-term expirations (30-45 DTE for income, 60-90 DTE for protection)
     - Strike prices near current price (ATM ± 10%)
     - High open interest and tight bid-ask spreads
   - Create `options_chains.json` with filtered data

3. **Price Options and Calculate Greeks**
   - Use QuantLib pricing engine (not yet integrated)
   - Calculate for each option:
     - Theoretical value (Black-Scholes or binomial)
     - Delta (directional exposure)
     - Gamma (delta sensitivity)
     - Vega (volatility exposure)
     - Theta (time decay)
   - Compare market prices to theoretical values (identify mispricing)
   - Create `options_pricing.json`

4. **Design Overlay Strategy**
   - Based on `strategy_type` argument:

   **Covered Call**: Income generation
   - Sell out-of-money calls against long stock
   - Target: 1-2% monthly income, low probability of assignment
   - Optimize strike selection for yield vs upside retention

   **Protective Put**: Downside protection
   - Buy out-of-money puts for portfolio insurance
   - Target: Limit losses to X% (e.g., 10% stop-loss equivalent)
   - Optimize strike/expiration for cost vs protection level

   **Collar**: Income + protection
   - Sell OTM calls, buy OTM puts
   - Target: Zero-cost or low-cost hedge with capped upside
   - Optimize collar width for risk/reward

   - For selected strategy:
     - Calculate position sizing (contracts per 100 shares)
     - Estimate income or protection cost
     - Calculate breakeven points
     - Model payoff diagrams
   - Create `strategy_design.json`

5. **Risk Analysis with Options**
   - Extend portfolio risk analysis to include options overlay
   - Calculate:
     - Portfolio delta (net directional exposure)
     - Portfolio gamma (convexity risk)
     - Portfolio vega (volatility exposure)
     - Expected Shortfall with options positions
   - Stress test scenarios (market crash, volatility spike)
   - Create `options_risk_analysis.json`

6. **Generate Options Overlay Report**
   - Use `@derivatives-options-analyst` agent
   - Create `options_overlay.md` with:
     - **Strategy Summary**: Type, objective, key parameters
     - **Position Details**: Specific strikes, expirations, quantities
     - **P&L Scenarios**: Payoff at various stock prices and dates
     - **Greeks Summary**: Net portfolio Greeks with overlay
     - **Risk Assessment**: ES with options, stress test results
     - **Implementation**: Exact order entry instructions
     - **Monitoring**: When to adjust or roll positions

## Agents Used

- `@derivatives-options-analyst` - Options strategy design and analysis
- `@risk-analyst` - Risk assessment with options overlay

## Output Location

Save all artifacts to current session directory.

## Success Criteria

- `options_chains.json` with filtered options data
- `options_pricing.json` with theoretical values and Greeks
- `strategy_design.json` with specific overlay structure
- `options_risk_analysis.json` with portfolio Greeks and stress tests
- `options_overlay.md` with implementation plan

## Example Usage (Future)

```
/options-overlay covered-call
```

Design covered call strategy for income generation on existing positions.

```
/options-overlay protective-put
```

Design protective put strategy for downside insurance.

```
/options-overlay collar
```

Design zero-cost collar for capped upside/downside.

## Implementation Notes

- **QuantLib Integration**: Python bindings for pricing and Greeks
- **Options Data**: Use Intrinio or Polygon for real-time chains
- **Position Tracking**: Extend portfolio-state-server schema for options
- **Greeks Aggregation**: Portfolio-level Greeks = sum of position Greeks
- **IV Surface**: Track implied volatility by strike/expiration for better pricing

## Strategy Guidelines

**Covered Calls**:
- Sell 30-45 DTE calls
- Target delta 0.20-0.30 (70-80% probability OTM)
- Roll when 21 DTE or delta >0.50
- Annualized yield target: 12-15%

**Protective Puts**:
- Buy 60-90 DTE puts
- Target delta -0.10 to -0.20 (80-90% probability OTM)
- 5-10% OTM strikes (tail protection)
- Cost: 1-3% of portfolio value per quarter

**Collars**:
- Match call/put expiration
- Sell calls 5-10% OTM
- Buy puts 5-10% OTM
- Target zero cost or small credit

## Risk Management

- **Assignment Risk**: Monitor covered calls approaching ITM, roll early
- **Gamma Risk**: Avoid excessive short gamma near expiration
- **Vega Risk**: Be aware of volatility exposure, especially short options
- **Correlation**: Options strategies work best on low-correlation positions
- **Liquidity**: Only use options with tight bid-ask spreads (<5% of mid)

## Future Enhancements

- Add calendar spreads for volatility trading
- Implement iron condors for range-bound positions
- Add event-driven options strategies (earnings, dividends)
- Integrate vol surface forecasting for better entry/exit timing
