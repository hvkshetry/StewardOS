---
name: portfolio-review
description: Unified portfolio review workflow for both command-driven health checks and client review meeting preparation.
user-invocable: true
---

# /portfolio-review — Unified Portfolio Review

This skill is the canonical portfolio review workflow for the investment officer persona.

It supports two closely related modes in one playbook:

1. **Portfolio Health Check (default)**: positions, risk, drift, concentration, TLH, and actionable recommendations.
2. **Client Review Prep**: package-ready talking points, benchmark framing, and meeting action items.

## MCP Tool Map

- Portfolio baseline and performance: `ghostfolio.portfolio(operation="summary")`, `ghostfolio.portfolio(operation="performance", range="1y")`, `ghostfolio.portfolio(operation="dividends", range="1y")`
- Portfolio state, risk, drift, and TLH: `portfolio-analytics.get_condensed_portfolio_state`, `portfolio-analytics.analyze_portfolio_risk`, `portfolio-analytics.analyze_allocation_drift`, `portfolio-analytics.find_tax_loss_harvesting_candidates`, `portfolio-analytics.validate_account_taxonomy`
- Tax overlay: `household-tax.compare_tax_scenarios`
- Market/policy context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.search_market_news`, `policy-events.get_recent_bills`, `policy-events.get_federal_rules`
- Disclosure overlays: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`

## Execution Workflow

### 1. Establish Scope and Baseline

- Run `ghostfolio.portfolio(operation="summary")` for baseline context.
- Run `portfolio-analytics.validate_account_taxonomy` before scoped analysis.
- Run `portfolio-analytics.get_condensed_portfolio_state` for holdings/top positions/unrealized P&L.
- For scoped calls, pass `scope_account_types` as a JSON list (for example `["brokerage","401k","hsa","equity_comp"]`).

### 2. Run Risk and Concentration Checks

- Run `portfolio-analytics.analyze_portfolio_risk` for ES(97.5%), VaR, volatility, and max drawdown.
- If ES > 2.5%: flag **RISK ALERT LEVEL 3** and discourage new risk additions.
- Flag concentration issues (for example, any single position >10% or correlated concentration clusters).

### 3. Evaluate Allocation Drift and Trade Context

- Run `portfolio-analytics.analyze_allocation_drift` using IPS targets.
- Highlight assets beyond threshold drift (default 3-5%).
- Convert drift signals into clear buy/sell notional actions.

### 4. Run Tax Overlay and TLH Scan

- Run `portfolio-analytics.find_tax_loss_harvesting_candidates` (typically taxable accounts only).
- For taxable brokerage-only scans, use `scope_account_types=["brokerage"]`.
- Include wash sale constraints and estimated tax savings.
- If material decisions are pending, run `household-tax.compare_tax_scenarios`.

### 5. Add Optional Context Layers

- Macro context: `market-intel-direct.get_market_snapshot` and `market-intel-direct.search_market_news`.
- Policy context: `policy-events.get_recent_bills`, `policy-events.get_federal_rules`.
- Disclosure/insider overlays for concentrated names:
  - `sec-edgar.sec_edgar_filing(operation="recent", identifier="[TICKER]", limit=3)`
  - `sec-edgar.sec_edgar_insider(operation="summary", identifier="[TICKER]", days=180)`

### 6. Produce Outputs (Mode-appropriate)

#### A. Portfolio Health Check Output

```markdown
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

#### B. Client Review Prep Output

Build a meeting packet with:

- performance table with benchmark comparison,
- allocation current-vs-target summary,
- top contributors/detractors,
- concise market context,
- clear action items with dates and owners.

Suggested agenda:

1. Market overview (2-3 minutes)
2. Performance and attribution (5 minutes)
3. Allocation drift/rebalancing discussion (5 minutes)
4. Planning updates (5-10 minutes)
5. Confirmed action items (5 minutes)

## Constraints and Notes

- This is advisory only; no direct trade authority.
- Always report tool gaps explicitly. Never fabricate values.
- Prioritize client-relevant framing over metric dumping.
- Keep recommendations traceable to tool outputs and assumptions.
