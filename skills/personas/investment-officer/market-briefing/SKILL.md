---
name: market-briefing
description: |
  Morning market snapshot combining direct market data, policy events,
  portfolio positioning, and risk metrics.
user-invocable: false
---

# Market Briefing

## Workflow

### Step 1: Market Overview (market-intel-direct)

Pull current market data:
- Major indices: S&P 500, NASDAQ, DJIA, Russell 2000
- Treasury proxies: ^IRX, ^TNX, ^TYX
- Commodities: WTI (CL=F), Gold (GC=F)
- Volatility: VIX
- Crypto proxies (if relevant): BTC-USD, ETH-USD

Use:
- `market-intel-direct.get_market_snapshot`
- `market-intel-direct.get_fred_series` for macro series where needed (CPI, Fed funds, unemployment)
- `market-intel-direct.get_cftc_cot_snapshot` for latest positioning in key contracts

### Step 2: Portfolio Position & Risk (portfolio-analytics + ghostfolio)

- `portfolio-analytics.get_condensed_portfolio_state` — scoped holdings and top concentration
- `portfolio-analytics.analyze_portfolio_risk` — verify ES < 2.5% binding constraint
- `ghostfolio.portfolio(operation="performance", range="1m")` — recent realized performance path

### Step 3: News Scan (market-intel-direct)

- `market-intel-direct.search_market_news` for top holdings and macro themes
- Keep to last 24-72 hours
- GDELT rule: query terms must be 3+ characters

### Step 4: Company Filings & Insider Flow (sec-edgar)

- For top holdings, pull latest filing context:
  - `sec-edgar.sec_edgar_filing(operation="recent", identifier="[TICKER]", limit=5)`
- If a new 10-K/10-Q exists, extract:
  - `sec-edgar.sec_edgar_filing(operation="sections", identifier="[TICKER]", accession_number="[ACCESSION]", form_type="[10-K|10-Q]")`
- For insider pulse:
  - `sec-edgar.sec_edgar_insider(operation="summary", identifier="[TICKER]", days=180)`

### Step 5: Policy & Regulatory (policy-events)

- `policy-events.get_recent_bills` for legislative activity
- `policy-events.get_federal_rules` for Federal Register activity
- Pull details only for relevant items:
  - `policy-events.get_bill_details`
  - `policy-events.get_rule_details`

### Step 6: Calendar Awareness

- Upcoming hearings: `policy-events.get_upcoming_hearings`
- Key macro release schedule: `market-intel-direct.get_macro_release_calendar`
- Tax deadlines (quarterly estimates, filing windows)

### Step 7: Output

Present as a concise briefing:

```
## Market Briefing — [Date]

### Markets
| Asset | Level | Change |
|-------|-------|--------|

### Portfolio
- Investments (ex-cash): $X | Cash: $Y | Net worth total: $Z
- ES (97.5%): X.XX% [OK/ALERT]
- Top concentration: [symbol, weight]

### Key News
1. [Headline] — [Impact on portfolio]
2. ...

### Policy Watch
- [Any material policy developments]

### Calendar This Week
- [Hearings, macro events, tax deadlines]

### Action Items
- [Any recommended actions based on above]
```

Value-label rule:
- Always present portfolio totals as `investments_value_ex_cash`, `cash_balance`, and `net_worth_total`.
- Do not present raw Ghostfolio field names without mapping.
