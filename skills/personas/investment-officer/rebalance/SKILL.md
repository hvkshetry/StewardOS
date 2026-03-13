---
name: rebalance
description: Analyze portfolio allocation drift and generate rebalancing trade recommendations across accounts. Considers tax implications, transaction costs, and wash sale rules.
user-invocable: false
---

# Portfolio Rebalance

This skill is the corrective-action engine that `portfolio-review` should call whenever a hard gate or threshold trigger requires action.

## Internal MCP Tool Map

- Current state: `portfolio-analytics.get_condensed_portfolio_state`, `portfolio-analytics.validate_account_taxonomy`
- Risk: `portfolio-analytics.analyze_portfolio_risk`, `portfolio-analytics.analyze_hypothetical_portfolio_risk`
- Drift: `portfolio-analytics.analyze_allocation_drift`, `portfolio-analytics.analyze_bucket_allocation_drift`
- Barbell gap math: `portfolio-analytics.classify_barbell_buckets`
- TLH and tax overlay: `portfolio-analytics.find_tax_loss_harvesting_candidates`; use `household-tax.assess_exact_support` only for supported exact household-tax cases
- Convex candidate ranking: `market-intel-direct.rank_convex_candidates`

## Workflow

### Step 1: Establish current state

- Run `portfolio-analytics.get_condensed_portfolio_state`
- Run `portfolio-analytics.validate_account_taxonomy`
- Run `portfolio-analytics.analyze_portfolio_risk`
- Run `portfolio-analytics.classify_barbell_buckets`

### Step 2: Determine the repair objective

Always solve in this order:

1. get ES below `2.5%`
2. raise hyper-safe to at least `15%`
3. raise convex to at least `10%`
4. reduce fragile-middle toward `70%`
5. clean up residual IPS drift and tax inefficiency

If ES is critical, do not let drift cleanup override the de-risking objective.

### Step 3: Funding order

Rank sells in this order:

- tax-deferred high-risk trims first
- taxable TLH-eligible losers second
- taxable gain realizations third

Use `include_decomposition=true` when needed to identify the biggest component-VaR contributors.

### Step 4: ES-driven repair

When `risk.status == "critical"` or `illiquid_overlay.adjusted_es_975_1d > 0.025`:

- estimate a first-pass trim set from the highest-risk symbols
- prefer reducing overlapping equity beta before cutting diversifiers
- do not recommend new risk-adding trades until the verified post-plan ES is back below limit

### Step 5: Barbell repair

Use `portfolio-analytics.classify_barbell_buckets` gap outputs directly:

- `safe_gap_pct/value`
- `convex_gap_pct/value`
- `fragile_excess_pct/value`

Then:

- fill the safe gap first when ES is still binding
- fill the convex gap second using ranked convex candidates
- use remaining trims to reduce fragile-middle

### Step 6: Convex implementation

When convex is below target:

- run `market-intel-direct.rank_convex_candidates`
- prefer the `primary_path_shortlist` for the verified recommendation
- keep options-based ideas in `Advanced Alternatives` unless and until overlay verification is supported for options structures

Important:

- `TLT` is conditional, not default
- gold / managed futures / tail-risk ETFs should usually rank better in inflationary or stagflationary setups
- options candidates are valid ideas only when account capability supports them

### Step 7: Verification

Do not pretend to verify by mentally adjusting weights.

- Use `portfolio-analytics.analyze_hypothetical_portfolio_risk(target_allocations=...)`
- Require the primary path to show:
  - `verification_pass == true`
  - proposed `ES(97.5%) < 2.5%`
  - post-plan barbell closer to policy targets

### Step 8: Tax overlay

- run `portfolio-analytics.find_tax_loss_harvesting_candidates`
- avoid wash-sale conflicts
- if taxable gains are material, assess whether the case is inside the exact household-tax scope before using that server

## Output Contract

The rebalance output should include:

- current constraint summary
- proposed trade list by wrapper/account
- primary path
- lower-tax alternative
- verification block from `analyze_hypothetical_portfolio_risk`
- post-plan barbell summary
- estimated tax impact
- unresolved caveats

## Constraints

- ES `<= 2.5%` is binding
- the verified recommendation must be wrapper-aware and tax-aware
- options-based convex ideas can be shown, but do not make them the primary recommended path until the risk-verification layer supports them directly
