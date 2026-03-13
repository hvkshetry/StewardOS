---
name: market-briefing
description: Morning market snapshot — indices, yields, commodities, VIX, currencies, macro flow, news, filings, and policy context.
user-invocable: true
---

# /market-briefing — Morning Market Snapshot

Produce a concise, scannable market briefing covering current conditions and key developments.

## MCP Tool Map

- Market data: `market-intel-direct.get_market_snapshot`
- Macro flow: `market-intel-direct.get_cftc_cot_snapshot`, `market-intel-direct.get_macro_release_calendar`
- News: `market-intel-direct.search_market_news`
- SEC filings: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`
- Policy context: `policy-events.get_recent_bills`, `policy-events.get_federal_rules`

## Workflow

### Step 1: Market Overview

- Major indices (S&P 500, DJIA, Nasdaq, Russell 2000)
- Treasury yields (2Y, 10Y, 30Y)
- Commodities (oil, gold)
- VIX level and percentile
- Key currency pairs (DXY, EUR/USD, USD/JPY)

### Step 2: Macro Flow

- CFTC positioning snapshot for key contracts
- Upcoming macro releases from the release calendar

### Step 3: News Scan

- Holdings-relevant news from the last 24 hours
- Broad macro themes and market-moving headlines

### Step 4: Filings Watch

- New SEC filings for tracked companies
- Notable insider activity

### Step 5: Policy Watch

- Active legislation with market relevance
- Regulatory filings and proposed rules

### Step 6: Calendar

- Earnings this week
- Economic data releases
- Tax deadlines

## Output

Present as a concise, scannable briefing. Prioritize actionable information.

Total target: readable in under 3 minutes.
