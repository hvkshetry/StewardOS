---
name: portfolio-review
description: >
  This skill should be used when the user asks for a portfolio review, portfolio
  health check, risk check, portfolio risk analysis, concentration check,
  allocation drift analysis, tax loss harvesting scan, or client review meeting
  prep. It produces a full diagnostic covering positions, risk (ES, VaR,
  volatility, vol regime, Student-t fit, illiquid overlay), allocation drift,
  TLH candidates, and actionable recommendations. For a formatted client-facing
  report without the diagnostic depth, use client-report instead.
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
- Illiquid risk pre-flight: `risk-model-config` skill (assembles `illiquid_overrides` from `finance-graph`)
- Tax overlay: `household-tax.compare_scenarios`
- Market/policy context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.search_market_news`, `policy-events.get_recent_bills`, `policy-events.get_federal_rules`
- Disclosure overlays: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`

## Execution Workflow

### 1. Establish Scope and Baseline

- Run `ghostfolio.portfolio(operation="summary")` for baseline context.
- Run `portfolio-analytics.validate_account_taxonomy` before scoped analysis.
- Run `portfolio-analytics.get_condensed_portfolio_state` for holdings/top positions/unrealized P&L.
- For scoped calls, pass `scope_account_types` as a JSON list (for example `["brokerage","401k","hsa","equity_comp"]`).

### 2. Run Risk and Concentration Checks

- If the portfolio contains illiquid or private holdings, run the `risk-model-config` skill first to assemble `illiquid_overrides` from finance-graph metadata.
- Run `portfolio-analytics.analyze_portfolio_risk(risk_model="auto", include_fx_risk=true, illiquid_overrides=<from risk-model-config if applicable>)` for ES(97.5%), VaR, volatility, max drawdown, Student-t fit, FX exposure, and vol regime.
- If `risk_data_integrity.weight_coverage_pct < 0.90`: note that risk is computed on a partial portfolio and tail risk is likely understated.
- If `risk.status == "unreliable"`: note coverage below 50% and treat all risk metrics as directional only.
- If `risk.status == "critical"` or `illiquid_overlay.adjusted_es_975_1d > 0.025`: flag **RISK ALERT LEVEL 3** and discourage new risk additions.
- Review `vol_regime.current_regime` — if elevated or crisis, highlight the short-vs-long vol ratio and `stress_es_975_1d`.
- If `risk-model-config` produced stressed overrides (regime ≠ normal), report both base and stressed ES side-by-side.
- Review `risk.student_t_fit` — if `fat_tailed: true`, note the degrees-of-freedom and parametric vs historical ES difference.
- For decomposition detail (component VaR, risk attribution), use `include_decomposition=true`.
- Flag concentration issues (for example, any single position >10% or correlated concentration clusters).

### 3. Evaluate Allocation Drift and Trade Context

- Run `portfolio-analytics.analyze_allocation_drift` using IPS targets.
- Highlight assets beyond threshold drift (default 3-5%).
- Convert drift signals into clear buy/sell notional actions.

### 4. Run Tax Overlay and TLH Scan

- Run `portfolio-analytics.find_tax_loss_harvesting_candidates` (typically taxable accounts only).
- For taxable brokerage-only scans, use `scope_account_types=["brokerage"]`.
- Include wash sale constraints and estimated tax savings.
- If material decisions are pending, run `household-tax.compare_scenarios`.

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

### Risk Data Integrity
- Weight Coverage: XX.X% | Missing: [symbols]
- Model: [resolved model: historical or student_t] | Tail Observations: N

### Risk
- ES (97.5%): X.XX% [OK/CRITICAL/UNRELIABLE] (historical: X.XX% | parametric: X.XX%)
- VaR (95%): X.XX% | VaR (97.5%): X.XX%
- Annualized Vol: X.XX% | Max Drawdown: X.XX%
- Student-t fit: df=X.X [fat-tailed: yes/no]
- Vol Regime: [low/normal/elevated/crisis] (ratio: X.XX)
- FX Exposure: X.X% non-USD [adjusted: yes/no]

### Illiquid Overlay (if applicable)
- Illiquid Weight: X.X% | Base Adjusted ES: X.XX%
- Stressed ES (regime-adjusted): X.XX% [only if regime ≠ normal]
- Positions: [list with vol/ρ assumptions, staleness flags]

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
