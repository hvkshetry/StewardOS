---
name: investment-proposal
description: Build a tax-aware investment proposal from current household holdings, risk limits, and stated objectives.
user-invocable: true
---

# /investment-proposal

Create a portfolio recommendation document suitable for advisory discussion.

## MCP Tool Map

- Current state: `ghostfolio.portfolio`, `portfolio-analytics.get_condensed_portfolio_state`
- Risk limits: `portfolio-analytics.analyze_portfolio_risk`
- Drift and reallocation: `portfolio-analytics.analyze_allocation_drift`
- Tax overlay: `portfolio-analytics.find_tax_loss_harvesting_candidates`; use `household-tax.assess_exact_support` only for narrow exact household-tax cases
- Macro context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.get_macro_context_panel`

## Workflow

### Step 1: Objectives and Constraints

- Confirm return objective, liquidity horizon, drawdown tolerance, and account constraints.
- Confirm ES <= 2.5% binding constraint.

### Step 2: Baseline Portfolio

- Pull summary, scoped holdings, concentration, and current risk.
- Identify concentration and wrapper-level inefficiencies.

### Step 3: Proposed Allocation

- Define target allocation by asset sleeve.
- Use drift analysis outputs to convert target vs current into proposal trades.
- Prioritize tax-advantaged wrappers for turnover.

### Step 4: Tax and Risk Validation

- Evaluate TLH opportunities where taxable losses exist.
- Run tax scenarios for major realization choices.
- Re-check risk metrics; if ES breaches 2.5%, revise down risk budget.

### Step 5: Proposal Output

- Proposed allocation and rationale.
- Suggested trade list with tax notes.
- Risk before/after summary.
- Implementation sequencing and monitoring plan.
