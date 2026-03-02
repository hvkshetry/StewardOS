---
name: client-report
description: Generate a client-facing portfolio report with performance, risk, allocation, and action items using MCP-first data sources.
user-invocable: true
---

# /client-report

Produce a concise, client-facing periodic report.

## MCP Tool Map

- Portfolio facts: `ghostfolio.portfolio`, `portfolio-analytics.get_condensed_portfolio_state`
- Risk and drift: `portfolio-analytics.analyze_portfolio_risk`, `portfolio-analytics.analyze_allocation_drift`
- Market context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.search_market_news`
- Disclosure context for top names: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`

## Workflow

### Step 1: Reporting Scope

- Confirm period: MTD, QTD, YTD, 1Y, custom.
- Confirm household scope: entity, wrapper, account types.
- Confirm benchmark framing and IPS targets.

### Step 2: Portfolio Snapshot

- Pull `ghostfolio.portfolio(operation="summary")`.
- Pull `ghostfolio.portfolio(operation="performance", range="1y")`.
- Pull `ghostfolio.portfolio(operation="dividends", range="1y")`.
- Pull `portfolio-analytics.get_condensed_portfolio_state` for positions and concentration.

### Step 3: Risk and Allocation

- Pull `portfolio-analytics.analyze_portfolio_risk` and report ES, VaR, drawdown, volatility.
- Pull `portfolio-analytics.analyze_allocation_drift` versus IPS targets.
- If ES > 2.5%, include CRITICAL risk alert language.

### Step 4: Market and Policy Context

- Pull `market-intel-direct.get_market_snapshot` for index/rates/vol backdrop.
- Pull `market-intel-direct.search_market_news` for relevant portfolio/macro headlines.
- Optionally pull `policy-events.get_recent_bills` and `policy-events.get_federal_rules` for policy context.

### Step 5: Report Output

- Executive summary.
- Performance table and attribution highlights.
- Risk section with ES constraint status.
- Allocation drift and rebalancing notes.
- Tax-aware notes and action items.
- Data gaps section if any tools returned empty/no data.
