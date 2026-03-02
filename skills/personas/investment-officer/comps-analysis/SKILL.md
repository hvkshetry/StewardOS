---
name: comps-analysis
description: Build public comparable-company valuation ranges to anchor private and illiquid holdings valuation.
user-invocable: false
---

# Comparable Company Analysis

Estimate valuation bands using relevant public comparables.

## MCP Tool Map

- Peer discovery and company context: `sec-edgar.sec_edgar_company`
- Financial metrics and statements: `sec-edgar.sec_edgar_financial`
- Market pricing context: `market-intel-direct.get_symbol_history`, `market-intel-direct.get_market_snapshot`
- Optional headline context: `market-intel-direct.search_market_news`

## Workflow

### Step 1: Peer Set

- Select 5-12 comparables by business model, growth, margins, and geography.
- Flag outliers and rationale for inclusion/exclusion.

### Step 2: Metric Normalization

- Collect revenue growth, EBITDA margin, leverage, and earnings quality proxies.
- Normalize for one-time events where possible.

### Step 3: Multiple Framework

- Build EV/Revenue and EV/EBITDA ranges.
- Apply discount/premium adjustments for size, liquidity, governance, and concentration.

### Step 4: Output

- Comparable table.
- Valuation range with low/base/high cases.
- Sensitivity to peer inclusion and multiple spread.
