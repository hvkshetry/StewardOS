---
description: Quarterly performance attribution and benchmark comparison
allowed-tools: mcp__portfolio-state-server__get_portfolio_state, mcp__risk-server__analyze_portfolio_risk, mcp__openbb-curated__equity_price_historical, mcp__openbb-curated__index_price_historical, mcp__openbb-curated__etf_holdings, Write
argument-hint: <benchmark_symbol> (e.g., "SPY", "AGG", "VT")
---

Perform comprehensive quarterly performance review with attribution analysis and benchmark comparison.

## Prerequisites

Portfolio state must be current with historical transaction data. Run `/import-portfolio` first if needed.

## Workflow Steps

1. **Get Portfolio Historical Performance**
   - Retrieve portfolio state with `mcp__portfolio-state-server__get_portfolio_state`
   - Extract:
     - Current positions and values
     - Historical transactions and cash flows
     - Realized gains/losses by period
     - Dividend/interest income received
   - Calculate time-weighted returns for:
     - 1 month trailing
     - 3 months trailing (quarterly)
     - 12 months trailing (annual)
     - Year-to-date (YTD)

2. **Get Benchmark Performance**
   - Retrieve benchmark historical prices with `mcp__openbb-curated__index_price_historical`
   - Use specified benchmark (default: SPY for equity-heavy portfolios)
   - Calculate benchmark returns for same periods:
     - 1M, 3M, 12M, YTD
   - If multiple benchmarks needed (e.g., 60/40 portfolio):
     - Get equity benchmark (SPY)
     - Get fixed income benchmark (AGG)
     - Calculate blended benchmark return

3. **Performance Attribution**
   - Break down portfolio returns by:
     - **Asset Class**: Equity vs Fixed Income vs Cash
     - **Sector**: Technology, Healthcare, Financials, etc.
     - **Geography**: US vs International vs Emerging Markets
     - **Security Selection**: Individual position contribution
   - For each component:
     - Calculate contribution to total return
     - Compare to benchmark allocation
     - Identify over/under performance
   - Create `attribution.json` with detailed breakdown

4. **Risk-Adjusted Metrics**
   - Get portfolio risk metrics with `mcp__risk-server__analyze_portfolio_risk`
   - Calculate:
     - Sharpe ratio (return per unit of volatility)
     - Sortino ratio (return per unit of downside risk)
     - Maximum drawdown
     - Value at Risk (VaR)
     - Expected Shortfall (ES)
   - Compare portfolio risk metrics to benchmark
   - Create `risk_adjusted_metrics.json`

5. **Holdings Analysis**
   - Identify top performers and detractors
   - For each position:
     - Calculate period return
     - Calculate contribution to portfolio return
     - Compare to sector/benchmark
   - For ETFs/funds, optionally get holdings with `mcp__openbb-curated__etf_holdings`
   - Create `holdings_performance.json` with position-level detail

6. **Generate Performance Report**
   - Use `@risk-analyst` and `@ic-memo-generator` agents
   - Create `performance_report.md` with:
     - **Executive Summary**: Portfolio vs benchmark performance
     - **Return Summary**: Tabular view of 1M/3M/12M/YTD returns
     - **Attribution Analysis**: What drove performance (asset class, sector, selection)
     - **Top Contributors**: Best performing positions
     - **Top Detractors**: Worst performing positions
     - **Risk-Adjusted Performance**: Sharpe, Sortino, drawdown vs benchmark
     - **Outlook**: Positioning for next period
   - Create `performance_summary.json` with key metrics

## Agents Used

- `@risk-analyst` - Risk metrics and attribution analysis
- `@ic-memo-generator` - Executive summary and synthesis

## Output Location

Save all artifacts to current session directory.

## Success Criteria

- `attribution.json` with performance breakdown by asset class/sector/position
- `risk_adjusted_metrics.json` with Sharpe/Sortino/drawdown vs benchmark
- `holdings_performance.json` with position-level returns
- `performance_report.md` with comprehensive analysis
- `performance_summary.json` with executive metrics

## Example Usage

```
/performance-review SPY
```

This will generate quarterly performance review comparing portfolio to S&P 500 (SPY).

For blended benchmarks:
```
/performance-review 60/40 (60% SPY, 40% AGG)
```

## Performance Calculation Notes

- **Time-Weighted Return**: Eliminates impact of cash flows (deposits/withdrawals)
- **Money-Weighted Return** (IRR): Includes cash flow timing impact
- **Contribution**: Position return × position weight
- **Attribution**: Decomposes portfolio return into allocation and selection effects
- **Sharpe Ratio**: (Return - Risk-free rate) / Volatility
- **Sortino Ratio**: (Return - Risk-free rate) / Downside deviation

## Quarterly Review Schedule

- **Q1 (Jan-Mar)**: Review full prior year, set new year goals
- **Q2 (Apr-Jun)**: Mid-year check, adjust if needed
- **Q3 (Jul-Sep)**: Third quarter check, plan year-end positioning
- **Q4 (Oct-Dec)**: Year-end review, prepare for next year

## Notes

- All performance data calculated from portfolio-state-server transaction history
- Benchmark data from OpenBB providers (YFinance, FMP)
- Risk metrics use 3-year lookback for volatility calculations
- Attribution uses GICS sector classifications where available
- Tool-first data policy: All metrics include provenance and timestamps
