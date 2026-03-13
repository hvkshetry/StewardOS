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

This skill is the canonical investment-officer review workflow.

Default behavior:

1. run a readiness check,
2. run the core diagnostic,
3. flag hard-gate breaches and action-triggering thresholds,
4. produce a corrective path when action is required,
5. verify the primary path with internal MCP tools,
6. explain every action-triggering metric in plain language.

This is not a diagnostic-only note anymore. When a trigger breaches, the review must recommend a path.

## Internal MCP Tool Map

- Baseline and state: `ghostfolio.portfolio(operation="summary")`, `portfolio-analytics.validate_account_taxonomy`, `portfolio-analytics.get_condensed_portfolio_state`
- Core risk: `portfolio-analytics.analyze_portfolio_risk`, `portfolio-analytics.analyze_hypothetical_portfolio_risk`
- Drift and TLH: `portfolio-analytics.analyze_allocation_drift`, `portfolio-analytics.analyze_bucket_allocation_drift`, `portfolio-analytics.find_tax_loss_harvesting_candidates`
- Practitioner layers: `portfolio-analytics.compute_ruin_scenario`, `portfolio-analytics.classify_barbell_buckets`, `market-intel-direct.get_shiller_cape`, `market-intel-direct.compute_market_temperature`, `market-intel-direct.rank_convex_candidates`
- Illiquid overlay inputs: `risk-model-config` skill plus `finance-graph.get_net_worth`
- Hard-gate overlay: `practitioner-heuristics` skill
- Corrective-action workflow: `rebalance` skill
- Tax overlay: `household-tax.assess_exact_support` only for narrow supported exact cases
- Context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.search_market_news`, `policy-events.*`, `sec-edgar.*`

## Review Readiness

Run these checks before writing the review. If a blocking layer fails, state that the review is incomplete and surface the gap near the top.

Blocking:

- `portfolio-analytics.validate_account_taxonomy(strict=false)`
- `portfolio-analytics.get_condensed_portfolio_state`
- `portfolio-analytics.analyze_portfolio_risk`
- `portfolio-analytics.classify_barbell_buckets`
- `portfolio-analytics.find_tax_loss_harvesting_candidates`
- `finance-graph.get_net_worth`
- `market-intel-direct.get_shiller_cape`
- `market-intel-direct.compute_market_temperature`
  - require `status == "complete"` for a complete temperature read

If `compute_market_temperature.status == "incomplete"`, do not present the temperature score as if it were complete. Report the missing components explicitly.

## Action-Triggering Metrics

These metrics trigger corrective action, not just commentary.

Hard triggers:

- ES above `2.5%`
- illiquidity above `25%` of household net worth
- employer-linked liquid exposure above `15%`

Threshold triggers:

- hyper-safe below `15%`
- convex below `10%`
- fragile-middle above `70%`
- material allocation drift outside IPS bands
- actionable TLH set above the configured threshold

Context-only metrics:

- market temperature
- ruin scenarios
- Student-t fit
- volatility regime

These change urgency and sequencing, but they do not independently force trades.

## Execution Workflow

### 1. Establish scope and baseline

- Run `ghostfolio.portfolio(operation="summary")`.
- Run `portfolio-analytics.validate_account_taxonomy`.
- Run `portfolio-analytics.get_condensed_portfolio_state`.
- For scoped calls, pass `scope_account_types` as a native list value.

### 2. Run the quantitative risk engine

- If illiquid or private holdings matter, run `risk-model-config` first and pass `illiquid_overrides` into `portfolio-analytics.analyze_portfolio_risk`.
- Use `risk_model="auto"` and `include_fx_risk=true`.
- If `risk.status == "critical"` or `illiquid_overlay.adjusted_es_975_1d > 0.025`, issue `RISK ALERT LEVEL 3`.
- If `risk.status == "unreliable"`, state clearly that the tail metrics are directional only.
- If `include_decomposition=true` is needed for a corrective path, use it before ranking sells.

### 3. Run hard gates

Follow `practitioner-heuristics`:

- ES gate
- illiquidity gate
- employer concentration gate

If any hard gate fails, the review must say so before advisory context.

### 4. Run practitioner layers

- `portfolio-analytics.compute_ruin_scenario`
- `portfolio-analytics.classify_barbell_buckets`
  - use `safe_gap_pct/value`, `convex_gap_pct/value`, and `fragile_excess_pct/value`
- `market-intel-direct.get_shiller_cape`
- `market-intel-direct.compute_market_temperature`
- When convex is below target, run `market-intel-direct.rank_convex_candidates`

### 5. Produce corrective path when required

If any hard trigger or threshold trigger breaches, the review MUST call the `rebalance` skill logic and produce:

- `Primary Path`
- `Lower-Tax Alternative`
- `Verification`
- `Remaining Caveats`

The primary path must be verified with `portfolio-analytics.analyze_hypothetical_portfolio_risk` before it is presented as the recommendation.

### 6. Plain-language explanations

For every metric that directly triggers corrective action, include a short block with:

- `What this metric means`
- `Why it matters`
- `Threshold breached`
- `Why the recommended action addresses it`

Apply this to:

- ES
- illiquidity
- employer concentration
- hyper-safe gap
- convex gap
- fragile-middle excess
- any drift metric that directly drives a trade recommendation

### 7. Tax and implementation overlay

- Run `portfolio-analytics.find_tax_loss_harvesting_candidates`
- Use `scope_account_types=["brokerage"]` for brokerage-only TLH scans
- If material taxable decisions are involved, check `household-tax.assess_exact_support` first and only use the exact tools when the case is supported

### 8. Optional context

- Macro: `market-intel-direct.get_market_snapshot`, `market-intel-direct.search_market_news`
- Policy: `policy-events.get_recent_bills`, `policy-events.get_federal_rules`
- Disclosure/insider context for concentrated names: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`

## Output Contract

The review output should use this structure when action is required:

```markdown
## Portfolio Review — [Date]

### Review Readiness
- [complete / incomplete]
- Blocking gaps: [...]

### Summary
- Total liquid value: $X
- Household net worth: $Y
- Binding constraint: [ES / illiquidity / employer / none]

### Triggered Metrics
- [metric]: [status] | [threshold] | [brief explanation]

### Plain-Language Metric Explanations
- [one short block per triggering metric]

### Corrective Path
- Primary path: [wrapper-aware actions]
- Lower-tax alternative: [if different]
- Advanced alternatives: [for example options-based convex ideas, if allowed]

### Verification
- Proposed ES(97.5%): X.XX%
- Verification pass: true/false
- Post-plan barbell: X% safe / X% convex / X% fragile

### Remaining Caveats
- [tool gaps, tax caveats, mapping caveats, incomplete context]
```

If no hard trigger or threshold trigger breaches, keep the review diagnostic and do not invent trades.

## Constraints

- Advisory only. No trading authority.
- Do not fabricate data or approximate missing blocking inputs.
- ES `<= 2.5%` remains the binding constraint.
- Do not present a corrective path as the recommendation unless it has been verified with `analyze_hypothetical_portfolio_risk`.
