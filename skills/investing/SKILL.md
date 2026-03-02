---
name: investing
description: |
  Personal portfolio management and investment analysis skill. Use when: (1) Checking
  portfolio risk (ES, VaR, drawdown), (2) Running rebalancing or optimization, (3) Equity
  research and valuation, (4) Tax-loss harvesting analysis, (5) Policy/regulatory impact
  assessment, (6) Performance attribution and benchmarking. Tools: 7 investing-workspace
  MCP servers + ghostfolio-mcp for portfolio tracking.
---

# Investment Management

## Critical Constraint: ES < 2.5%

Expected Shortfall at 97.5% confidence must remain below 2.5%. This is the binding risk constraint. Check ES before and after any proposed trade or rebalance.

## Tool Mapping

| Task | Server | Key Tools |
|------|--------|-----------|
| Current holdings & allocations | portfolio-state | `get_positions`, `get_portfolio_summary`, `get_tax_lots` |
| Risk metrics (ES, VaR, drawdown) | risk | `calculate_es`, `calculate_var`, `stress_test`, `correlation_matrix` |
| Portfolio optimization | portfolio-optimization | `optimize_portfolio`, `efficient_frontier`, `black_litterman` |
| Tax analysis | tax | `get_tax_lots`, `calculate_gains`, `wash_sale_check` |
| Tax-loss harvesting | tax-optimization | `find_tlh_opportunities`, `simulate_harvest`, `tax_efficient_rebalance` |
| Market data & fundamentals | openbb-curated | `equity_price_historical`, `equity_fundamental_*`, `economy_*` |
| SEC filings | openbb-curated | `regulators_sec_section_extract`, `equity_fundamental_filings` |
| News & events | openbb-curated | `news_search` (GDELT — keywords must be 3+ chars) |
| Policy impact | policy-events | `search_bills`, `get_bill_detail`, `search_regulations` |
| Portfolio tracking | ghostfolio | `get_portfolio_summary`, `get_portfolio_performance`, `get_dividends` |

## Workflow: Daily Check

1. `get_portfolio_summary` — current value, allocation, cash position
2. `calculate_es` — verify ES < 2.5%
3. `get_positions` — check for any position > 10% of portfolio
4. `news_search` — scan for news on top holdings
5. Report: ES status, notable moves, concentration risk, news alerts

## Workflow: Rebalancing

1. `get_portfolio_summary` — current allocations
2. `optimize_portfolio` — target allocation (mean-variance or Black-Litterman)
3. `calculate_es` on proposed allocation — verify ES < 2.5%
4. `find_tlh_opportunities` — check for tax-loss harvesting before trading
5. `tax_efficient_rebalance` — generate trade list minimizing tax impact
6. Present: proposed trades, expected ES, tax impact, estimated costs

## Workflow: Equity Research

1. `equity_price_historical` — price trend and technicals
2. `equity_fundamental_*` — revenue, earnings, margins, valuation multiples
3. `equity_fundamental_filings` + `regulators_sec_section_extract` — read 10-K risk factors and MD&A
4. `news_search` — recent news and sentiment
5. `search_bills` / `search_regulations` — regulatory exposure
6. Present: thesis, valuation range, risks, position sizing recommendation

## Workflow: Tax Planning

1. `get_tax_lots` — all lots with cost basis and holding period
2. `calculate_gains` — realized and unrealized gains/losses by short/long-term
3. `find_tlh_opportunities` — losses available for harvesting
4. `wash_sale_check` — verify no wash sale violations
5. Present: tax liability estimate, TLH opportunities, wash sale risks

## Holistic Tax Planning

For tax decisions that span both investment and household income, coordinate with
**household-tax-mcp** (in personal-finance agent config):
- `estimate_quarterly_1040es` — includes investment income in quarterly estimate
- `compare_tax_scenarios` — model impact of Roth conversions, additional capital gains, etc.
- `compute_schedule_se` — relevant if self-employment income interacts with investment income

The investing-workspace tax servers handle investment-specific tax (wash sales, TLH,
cost basis). household-tax-mcp handles the full 1040 picture including SE tax.

## Key Rules

- **Tool-First Data**: ALL metrics must come from MCP tool calls with timestamps
- **No Fabrication**: If a tool returns no data, report the gap — never estimate
- **ES Binding**: Any recommendation that pushes ES > 2.5% must include a RISK ALERT
- **GDELT Queries**: Use full terms ("artificial intelligence" not "AI") — min 3 chars per keyword
- **SEC Sections**: Max 2 chunks per section, ~15K tokens total per extract call
