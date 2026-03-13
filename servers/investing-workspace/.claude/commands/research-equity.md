---
description: Comprehensive equity research analysis with factor exposures and valuation
allowed-tools: mcp__openbb-curated__equity_profile, mcp__openbb-curated__equity_fundamental_metrics, mcp__openbb-curated__equity_fundamental_income, mcp__openbb-curated__equity_fundamental_balance, mcp__openbb-curated__equity_estimates_consensus, mcp__openbb-curated__news_company, mcp__openbb-curated__equity_price_historical, Write
argument-hint: <tickers> (comma-separated, e.g., "AAPL,MSFT,GOOGL")
---

Perform comprehensive equity research on one or more tickers. This workflow generates a detailed analysis with fundamentals, valuation metrics, analyst consensus, and recent news.

## Workflow Steps

1. **Company Profile & Overview**
   - For each ticker, get company profile with `mcp__openbb-curated__equity_profile`
   - Extract:
     - Company name, sector, industry
     - Market cap and employee count
     - Description and business model
   - Create `company_profiles.json` with basic info

2. **Fundamental Analysis**
   - Get key metrics with `mcp__openbb-curated__equity_fundamental_metrics`
   - Get income statement with `mcp__openbb-curated__equity_fundamental_income`
   - Get balance sheet with `mcp__openbb-curated__equity_fundamental_balance`
   - Calculate and extract:
     - Profitability: ROE, ROA, gross/operating/net margins
     - Growth: Revenue growth, earnings growth
     - Leverage: Debt/Equity, Interest coverage
     - Efficiency: Asset turnover, inventory turnover
   - Create `fundamental_analysis.json` with key ratios

3. **Valuation & Price Performance**
   - Get historical prices with `mcp__openbb-curated__equity_price_historical` (1-year lookback)
   - Get analyst consensus with `mcp__openbb-curated__equity_estimates_consensus`
   - Extract:
     - Current P/E, P/B, P/S ratios
     - Price targets (high/low/mean/median)
     - Analyst recommendations (buy/hold/sell counts)
     - 52-week high/low, YTD return
   - Create `valuation_snapshot.json` with pricing metrics

4. **News & Sentiment Analysis**
   - Get recent news with `mcp__openbb-curated__news_company`
   - Focus on last 30 days
   - Categorize by:
     - Earnings announcements
     - Product launches
     - Regulatory/legal developments
     - Management changes
   - Create `news_summary.json` with key events and sentiment

5. **Generate Research Report**
   - Use `@equity-analyst` agent to synthesize findings
   - Create `equity_research.md` with:
     - Executive summary for each ticker
     - Comparative analysis (if multiple tickers)
     - Valuation vs. sector peers
     - Risk factors identified
     - Investment thesis (bull/bear cases)
     - Recommendation with price target

## Agents Used

- `@equity-analyst` - Lead analyst for synthesis
- `@market-scanner` - News and sentiment analysis (if needed)

## Output Location

Save all artifacts to current session directory.

## Success Criteria

- `company_profiles.json` with basic company info
- `fundamental_analysis.json` with key financial ratios
- `valuation_snapshot.json` with pricing and analyst data
- `news_summary.json` with recent developments
- `equity_research.md` with comprehensive analysis and recommendation

## Example Usage

```
/research-equity AAPL,MSFT,GOOGL
```

This will generate comparative research on Apple, Microsoft, and Google with fundamental analysis, valuation metrics, and investment recommendations.

## Notes

- All data comes from OpenBB providers (FMP, Intrinio, YFinance)
- Financial metrics use most recent reported periods (annual/quarterly)
- Analyst consensus combines multiple sources when available
- Tool-first data policy: All metrics include provenance and timestamps
