---
description: Quarterly tax planning with liability estimation and loss harvesting opportunities
allowed-tools: mcp__portfolio-state-server__get_portfolio_state, mcp__portfolio-state-server__simulate_sale, mcp__tax-server__calculate_comprehensive_tax, mcp__tax-optimization-server__find_tax_loss_harvesting_pairs, Write
argument-hint: <quarter> (e.g., "Q1", "Q2", "Q3", "Q4")
---

Perform comprehensive quarterly tax planning including estimated liability, tax loss harvesting opportunities, and wash sale compliance checks.

## Prerequisites

Portfolio state must be current. Run `/import-portfolio` first if needed.

## Workflow Steps

1. **Get Current Portfolio State**
   - Retrieve all positions and tax lots with `mcp__portfolio-state-server__get_portfolio_state`
   - Extract:
     - Realized gains/losses YTD
     - Unrealized gains/losses by lot
     - Income received (dividends, interest)
     - Short-term vs long-term breakdown

2. **Calculate Estimated Tax Liability**
   - Use `mcp__tax-server__calculate_comprehensive_tax` with:
     - Current year income sources
     - Realized capital gains/losses YTD
     - Ordinary dividends and qualified dividends
     - Interest income (taxable and tax-exempt)
   - Calculate for both federal and state (MA)
   - Include NIIT (Net Investment Income Tax) if applicable
   - Create `tax_estimate_<quarter>.json` with:
     - Estimated federal tax
     - Estimated state tax
     - Total estimated liability
     - Effective tax rate

3. **Identify Tax Loss Harvesting Opportunities**
   - Find TLH pairs with `mcp__tax-optimization-server__find_tax_loss_harvesting_pairs`
   - Parameters:
     - `correlation_threshold`: 0.95 (highly correlated substitutes)
     - `min_loss_threshold`: 1000 (minimum $1k loss to consider)
   - For each opportunity:
     - Calculate tax savings at current marginal rate
     - Identify highly-correlated replacement securities
     - Check wash sale rule compliance (30-day window)
   - Create `tlh_opportunities.json` with ranked list

4. **Simulate Sale Scenarios**
   - For top TLH opportunities, simulate sales with `mcp__portfolio-state-server__simulate_sale`
   - Test different cost basis methods (FIFO, HIFO, SpecID)
   - Extract:
     - Realized short-term vs long-term losses
     - Tax impact at federal/state level
     - Net portfolio value after tax savings
   - Create `sale_simulations.json` with comparative analysis

5. **Generate Tax Action Plan**
   - Use `@tax-advisor` agent to synthesize findings
   - Create `tax_plan_<quarter>.md` with:
     - **Executive Summary**: Current tax position and estimated liability
     - **YTD Tax Summary**: Realized gains/losses, income, effective rate
     - **TLH Opportunities**: Top 5-10 harvesting candidates with tax savings
     - **Wash Sale Warnings**: Any positions to avoid due to 30-day rule
     - **Quarterly Actions**: Specific trades recommended before quarter-end
     - **Year-End Planning**: Projected year-end liability and planning moves
   - Create `tax_actions.json` with actionable trade list

## Critical Constraints

- **Wash Sale Rule**: No repurchase of "substantially identical" securities within 30 days
- **Lot Selection**: Document cost basis method used (FIFO default)
- **State Taxes**: Always calculate both federal and state (MA) liability
- **NIIT**: Include 3.8% Net Investment Income Tax if AGI > threshold
- **Tool-first data**: All tax calculations must come from tax-server with provenance

## Agents Used

- `@tax-advisor` - Lead agent for tax planning synthesis

## Output Location

Save all artifacts to current session directory.

## Success Criteria

- `tax_estimate_<quarter>.json` with federal/state/NIIT liability
- `tlh_opportunities.json` with ranked harvesting candidates
- `sale_simulations.json` with tax impact of different scenarios
- `tax_plan_<quarter>.md` with comprehensive action plan
- `tax_actions.json` with specific trades to execute

## Example Usage

```
/tax-planning Q4
```

This will generate Q4 tax planning with year-end liability estimate, TLH opportunities, and actionable trade recommendations.

## Quarterly Planning Timeline

- **Q1 (Jan-Mar)**: Set baseline for year, early TLH if needed
- **Q2 (Apr-Jun)**: Mid-year check, adjust withholding if needed
- **Q3 (Jul-Sep)**: Q3 estimated payment, start year-end planning
- **Q4 (Oct-Dec)**: Final TLH window, realize/defer gains strategically

## Notes

- Tax calculations use current year tax tables (2018-2025 supported)
- TLH pairs based on 95%+ correlation over 3-year lookback
- Wash sale tracking includes both buys and sells
- All trades tracked by lot for accurate FIFO/HIFO/SpecID basis
