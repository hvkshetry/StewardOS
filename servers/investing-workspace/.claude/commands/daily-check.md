---
description: Run daily portfolio monitoring and risk assessment
allowed-tools: mcp__portfolio-state-server__get_portfolio_state, mcp__openbb-curated__news_company, mcp__policy-events-service__get_recent_bills, mcp__policy-events-service__get_federal_rules, mcp__risk-server__analyze_portfolio_risk, Write
---

Run my daily portfolio monitoring workflow. This is a lightweight check, not a full rebalancing.

## Prerequisites

Portfolio state must be current (imported within T+1 trading days). If state is stale, run `/import-portfolio` first.

## Workflow Steps

1. **Validate Portfolio State**
   - Get current portfolio state with `mcp__portfolio-state-server__get_portfolio_state`
   - Check `last_updated` timestamp
   - **FAIL FAST** if state is older than T+1 trading days
   - Alert user to run `/import-portfolio` if stale

2. **Scan Market & News**
   - Use `@market-scanner` agent to check overnight developments
   - Focus on news affecting portfolio holdings (use `mcp__openbb-curated__news_company`)
   - Check for policy events that could impact positions:
     - `mcp__policy-events-service__get_recent_bills`
     - `mcp__policy-events-service__get_federal_rules`
   - Create `market_scan.json` with sentiment and key events

3. **Check Portfolio Status**
   - Calculate overnight changes and allocation drift from portfolio state
   - Create `portfolio_check.json` with current metrics:
     - Total value and daily change
     - Asset class allocation
     - Top holdings and weights
     - Unrealized gains/losses

4. **Quick Risk Assessment with Gate Validation**
   - Run risk analysis with `mcp__risk-server__analyze_portfolio_risk`
   - Extract `executive_summary.es_975_1day` from response
   - Extract `executive_summary.halt_required` flag
   - **CRITICAL ES GATE**:
     - If `halt_required == true`, IMMEDIATELY HALT and alert user
     - If ES > 2.5%, HALT even if flag is false (defensive check)
     - ES @ 97.5% confidence MUST be ≤ 2.5% (BINDING CONSTRAINT)
   - **Concentration Gate**: Check 20% max per individual stock (funds exempt)
   - Create `risk_check.json` with current risk metrics and gate results

5. **Generate Daily Summary**
   - Create `daily_note.md` with:
     - Portfolio summary (total value, daily change)
     - Market summary (key developments, sentiment)
     - Risk status (ES level, concentration alerts)
     - Action items (rebalance needed? alerts?)
   - Alert if: ES > 2.5%, allocation drift > 5%, or daily loss > 5%

## Critical Constraints

- **ES ≤ 2.5%** at 97.5% confidence (HALT if exceeded)
- **Concentration**: Max 20% per individual stock (funds/ETFs exempt)
- **Tool-first data**: All metrics must come from MCP tool calls with provenance
- **State freshness**: Portfolio state must be T+1 or newer

## Agents Used

- `@market-scanner` - News and policy scanning
- `@risk-analyst` - Risk metrics and gate validation

## Output Location

Save all artifacts to current session directory for audit trail.

## Success Criteria

- `market_scan.json` with news sentiment and policy events
- `portfolio_check.json` with current allocation and changes
- `risk_check.json` with ES metrics and gate validation
- `daily_note.md` with actionable summary
