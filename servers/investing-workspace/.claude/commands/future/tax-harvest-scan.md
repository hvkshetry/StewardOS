---
description: Automated daily tax loss harvesting scan with actionable trade recommendations
allowed-tools: mcp__portfolio-state-server__get_portfolio_state, mcp__tax-optimization-server__find_tax_loss_harvesting_pairs, mcp__tax-server__calculate_comprehensive_tax, mcp__openbb-curated__equity_price_historical, Write
status: planned
prerequisites:
  - "Implement automated lot scoring algorithm (loss magnitude, holding period, correlation)"
  - "Add calendar scheduling for automated daily scans"
  - "Integrate with trade execution system for one-click harvesting"
  - "Add wash sale calendar tracking across all accounts"
argument-hint: <mode> (e.g., "scan", "auto-execute", "calendar-check")
---

Automated tax loss harvesting scanner with intelligent lot selection and wash sale compliance. This workflow identifies daily TLH opportunities and generates actionable trade recommendations.

## Prerequisites

**NOT YET IMPLEMENTED - FUTURE ENHANCEMENT**

Required integrations:
1. Automated lot scoring algorithm ranking TLH opportunities
2. Calendar scheduling system for daily automated scans
3. Wash sale tracking across all accounts (including spouse/dependent accounts)
4. Optional: Direct broker integration for automated execution

## Workflow Steps (When Implemented)

1. **Daily Price Update**
   - Get latest prices for all portfolio positions
   - Calculate intraday unrealized gains/losses
   - Flag positions with material losses (>$1,000 or >5% loss)

2. **Scan for TLH Opportunities**
   - Use `mcp__tax-optimization-server__find_tax_loss_harvesting_pairs` with enhanced scoring
   - For each position with unrealized loss:
     - Calculate total harvestable loss by lot
     - Identify short-term vs long-term lots
     - Find highly correlated replacement securities (95%+ correlation)
     - Score opportunity by:
       - Loss magnitude (larger = higher score)
       - Tax benefit (short-term > long-term)
       - Holding period (approaching 1-year anniversary = lower score)
       - Correlation of replacement (higher = better)
   - Create `tlh_scan_<date>.json` with ranked opportunities

3. **Wash Sale Compliance Check**
   - For each TLH candidate, check 30-day calendar:
     - **Lookback**: No purchases in prior 30 days
     - **Lookahead**: No planned purchases in next 30 days
     - **Cross-Account**: Check spouse and dependent accounts
     - **Replacement**: Verify replacement not "substantially identical"
   - Flag safe opportunities (no wash sale risk)
   - Create `wash_sale_calendar.json` with blocked dates

4. **Calculate Tax Impact**
   - For each safe opportunity, simulate sale and tax benefit
   - Use `mcp__tax-server__calculate_comprehensive_tax` to model:
     - Federal tax savings (short-term at ordinary rate, long-term at 15-20%)
     - State tax savings (MA rates)
     - NIIT impact (3.8% for high earners)
     - Total tax benefit of harvest
   - Model reinvestment in replacement security
   - Create `tax_impact_forecast.json`

5. **Generate Trade List**
   - Rank opportunities by tax benefit / transaction cost
   - Filter by:
     - Minimum tax benefit ($500+ recommended)
     - Liquidity of original and replacement securities
     - Transaction costs (commissions, spreads)
   - For each trade:
     - Specify lot selection (by acquisition date)
     - Provide exact sell and buy instructions
     - Calculate wash sale expiration date (safe to repurchase)
   - Create `tlh_trade_list_<date>.json`

6. **Generate TLH Report**
   - Use `@tax-advisor` agent
   - Create `tlh_scan_report_<date>.md` with:
     - **Executive Summary**: Total harvestable losses, estimated tax savings
     - **Top Opportunities**: Top 10 ranked by tax benefit
     - **Calendar**: Wash sale blocked periods
     - **Trade Instructions**: Exact orders to place
     - **Replacement Securities**: Ticker, correlation, rationale
     - **Follow-up**: When to review (e.g., next opportunity after wash sale clears)

## Agents Used

- `@tax-advisor` - Lead agent for TLH analysis

## Automation Modes

### Scan Mode (Default)
- Daily automated scan at market close
- Generate report with opportunities
- No automatic execution (manual review required)

### Auto-Execute Mode (Future)
- Same as scan mode, but automatically place trades if:
  - Tax benefit > $1,000
  - No wash sale risk
  - User has pre-authorized automation
- Send notification after execution

### Calendar Check Mode
- Review upcoming wash sale expiration dates
- Identify positions safe to repurchase
- Alert user of upcoming opportunities

## Output Location

Save all artifacts to current session directory with date stamp.

## Success Criteria

- `tlh_scan_<date>.json` with ranked opportunities
- `wash_sale_calendar.json` with blocked periods
- `tax_impact_forecast.json` with estimated savings
- `tlh_trade_list_<date>.json` with exact trade instructions
- `tlh_scan_report_<date>.md` with actionable recommendations

## Example Usage (Future)

```
/tax-harvest-scan scan
```

Daily scan for TLH opportunities with manual review.

```
/tax-harvest-scan calendar-check
```

Review wash sale calendar and upcoming opportunities.

```
/tax-harvest-scan auto-execute
```

Automated scan and execution (requires pre-authorization).

## Implementation Notes

### Lot Scoring Algorithm
```python
score = (
    loss_magnitude * 1.0 +
    tax_rate * loss_magnitude * 2.0 +  # Higher weight for tax benefit
    replacement_correlation * 0.5 +
    (1 if short_term else 0.5) * 1.0 -  # Prefer short-term losses
    min(days_until_long_term / 365, 1.0) * 0.3  # Penalty if close to LT
)
```

### Replacement Security Selection
- Use 3-year rolling correlation
- Minimum correlation: 0.95
- Prefer index ETFs over individual stocks
- Avoid "substantially identical" (e.g., different share classes)

Examples:
- VTI (Total Market) → ITOT or SCHB
- VOO (S&P 500) → SPY or IVV
- VWO (Emerging Markets) → IEMG or SPEM
- Individual stock → Sector ETF (e.g., AAPL → XLK)

### Wash Sale Rules
- **30-Day Window**: 30 days before and after sale
- **Substantially Identical**: Same CUSIP or near-identical securities
- **Cross-Account**: Includes spouse, dependents, IRAs, 401(k)s
- **Penalty**: Loss disallowed, added to cost basis of replacement

### Optimal Timing
- **Market Volatility**: More opportunities during corrections
- **End of Year**: Final TLH window before year-end
- **Limit Orders**: Use limit orders to harvest on intraday spikes
- **Rebalancing**: Combine TLH with regular rebalancing for efficiency

## Scheduling

**Daily Scan**: 4:30 PM ET (after market close)
- Update prices
- Scan for new opportunities
- Email report if opportunities > $1,000

**Weekly Review**: Friday 5 PM ET
- Aggregate week's opportunities
- Review wash sale calendar
- Plan trades for next week

**Monthly Check**: First trading day of month
- Review year-to-date harvesting
- Project year-end tax impact
- Adjust strategy if needed

## Risk Management

- **Tracking Error**: Ensure replacement maintains similar exposure
- **Transaction Costs**: Consider commissions and spreads
- **Market Risk**: Use limit orders to avoid poor execution
- **Compliance**: Strict wash sale rule adherence (IRS scrutiny high)

## Future Enhancements

- Machine learning for optimal harvest timing
- Integration with direct indexing (daily TLH on 100+ positions)
- Predictive modeling of future TLH opportunities
- Multi-account optimization (IRA vs taxable)
- Automated rebalancing combined with TLH
