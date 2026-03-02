---
name: portfolio-review
description: Full portfolio health check — positions, allocation drift, risk metrics, TLH opportunities, and concentration analysis.
user-invocable: true
---

# /portfolio-review — Portfolio Health Check

Comprehensive portfolio review using the condensed tool surface.

## MCP Tool Map

- Portfolio state: `ghostfolio.portfolio`, `portfolio-analytics.get_condensed_portfolio_state`
- Risk and drift: `portfolio-analytics.analyze_portfolio_risk`, `portfolio-analytics.analyze_allocation_drift`
- Tax overlays: `portfolio-analytics.find_tax_loss_harvesting_candidates`
- Market and policy context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.search_market_news`, `policy-events.get_recent_bills`
- Disclosure overlays: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`

## Steps

### 1. Portfolio State (ghostfolio + portfolio-analytics)

- `ghostfolio.portfolio(operation="summary")` — baseline value/performance context
- `portfolio-analytics.validate_account_taxonomy` — verify account tags for scoped analysis
- `portfolio-analytics.get_condensed_portfolio_state` — scoped holdings, top positions, unrealized P&L
- For scoped calls, pass `scope_account_types` as a JSON list, e.g. `["brokerage","401k","hsa","equity_comp"]` (not a comma-separated string)

### 2. Risk Check (portfolio-analytics)

- `portfolio-analytics.analyze_portfolio_risk` — ES(97.5%), VaR, volatility, max drawdown
- **If ES > 2.5%: RISK ALERT LEVEL 3 — flag immediately and discourage new trades**

### 3. Allocation Drift (portfolio-analytics)

- `portfolio-analytics.analyze_allocation_drift` with IPS targets
- Flag symbols drifting beyond configured threshold (default 3%)
- Convert drift to buy/sell notional recommendations

### 4. Concentration Analysis

- Use `get_condensed_portfolio_state` + `analyze_portfolio_risk` top positions
- Flag any single position > 10% and highlight cluster risk

### 5. Tax-Loss Harvesting Scan (portfolio-analytics)

- `portfolio-analytics.find_tax_loss_harvesting_candidates` scoped to taxable accounts
- For taxable brokerage-only scans, use `scope_account_types=["brokerage"]`
- Include estimated tax savings and replacement hints
- Note wash sale window constraints (30-day rule)

### 6. Performance & Income (ghostfolio)

- `ghostfolio.portfolio(operation="performance", range="1y")` — recent realized performance path
- `ghostfolio.portfolio(operation="dividends", range="1y")` — recent dividend income trend

### 7. Optional Market Context (market-intel-direct)

- `market-intel-direct.get_market_snapshot` — index/rates/volatility context
- `market-intel-direct.search_market_news` — relevant macro/holding headlines
- `market-intel-direct.get_cftc_cot_snapshot` — positioning context for rates/equity index contracts

### 8. Optional Disclosure Risk Overlay (sec-edgar)

- `sec-edgar.sec_edgar_filing(operation="recent", identifier="[TICKER]", limit=3)` for top concentrations
- If new 10-K/10-Q exists, extract:
  - `sec-edgar.sec_edgar_filing(operation="sections", identifier="[TICKER]", accession_number="[ACCESSION]", form_type="[10-K|10-Q]")`
- `sec-edgar.sec_edgar_insider(operation="summary", identifier="[TICKER]", days=180)` for insider activity context

### 8. Output

```
## Portfolio Review — [Date]

### Summary
- Total Value: $X | Unrealized P&L: $Y
- Scope: [entity/wrapper/account types]

### Risk
- ES (97.5%): X.XX% [OK/ALERT]
- VaR (95%): X.XX%
- Max Drawdown: X.XX%

### Allocation Drift
| Symbol | Current | Target | Drift | Action |
|--------|---------|--------|-------|--------|

### TLH Opportunities
| Symbol | Loss | Loss % | Est. Tax Savings | Replacement |
|--------|------|--------|------------------|-------------|

### Concentration Alerts
- [Any flags]

### Recommendations
1. [Specific, actionable recommendations]
```
