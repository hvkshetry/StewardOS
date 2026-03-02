---
name: portfolio-review
description: Prepare for client review meetings with portfolio performance summary, allocation analysis, talking points, and action items.
user-invocable: false
---

# Client Review Prep

## MCP Tool Map

- Portfolio baseline and performance: `ghostfolio.portfolio(operation="summary")`, `ghostfolio.portfolio(operation="performance", range="1y")`
- Risk and concentration: `portfolio-analytics.analyze_portfolio_risk`, `portfolio-analytics.get_condensed_portfolio_state`
- Drift and rebalancing context: `portfolio-analytics.analyze_allocation_drift`
- Tax overlays: `portfolio-analytics.find_tax_loss_harvesting_candidates`, `household-tax.compare_tax_scenarios`
- Market and policy context: `market-intel-direct.get_market_snapshot`, `policy-events.get_recent_bills`, `policy-events.get_federal_rules`
- Disclosure overlays for concentrated names: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_insider`

## Workflow

### Step 1: Client Context

Gather or look up:
- **Client name** and household members
- **Account types**: Taxable, IRA, Roth, 401(k), trust, etc.
- **Total AUM** across accounts
- **Investment Policy Statement (IPS)**: Target allocation, risk tolerance, constraints
- **Life stage**: Accumulation, pre-retirement, retirement, legacy
- **Last meeting date** and any outstanding action items

### Step 2: Portfolio Performance

For each account and the household aggregate:

| Metric | QTD | YTD | 1-Year | 3-Year | Since Inception |
|--------|-----|-----|--------|--------|----------------|
| Portfolio return | | | | | |
| Benchmark return | | | | | |
| Alpha | | | | | |

**Performance Attribution:**
- Which asset classes / positions drove returns?
- Top 3 contributors and top 3 detractors
- Any outsized single-position impact?
- Use `ghostfolio.portfolio(operation="performance", range="1y")` and `portfolio-analytics.get_condensed_portfolio_state`.

### Step 3: Allocation Review

Current vs. target allocation:

| Asset Class | Target | Current | Drift | Action |
|------------|--------|---------|-------|--------|
| US Large Cap | | | | |
| US Mid/Small | | | | |
| International Developed | | | | |
| Emerging Markets | | | | |
| Fixed Income | | | | |
| Alternatives | | | | |
| Cash | | | | |

Flag any drift exceeding the IPS rebalancing threshold (typically 3-5%).
Use `portfolio-analytics.analyze_allocation_drift` for the drift table.

### Step 4: Talking Points

Generate a meeting agenda:

1. **Market overview** (2-3 min): Brief macro context and outlook
2. **Portfolio performance** (5 min): How did we do? Why?
3. **Allocation review** (5 min): Any rebalancing needed?
4. **Planning updates** (5-10 min):
   - Life changes? (job, health, family, home, education)
   - Income needs changing?
   - Tax situation updates
   - Estate planning updates
5. **Action items** (5 min): What are we doing before next meeting?

When preparing the opening market context, use `market-intel-direct.get_market_snapshot`.

### Step 5: Proactive Recommendations

Based on the review, suggest:
- Rebalancing trades (if drift exceeds thresholds)
- Tax-loss harvesting opportunities
- Cash deployment or withdrawal planning
- Roth conversion opportunities (if applicable)
- Beneficiary updates or estate planning needs
- Insurance review (life, disability, LTC)
- For top concentration names, add SEC disclosure and insider summary overlays.

### Step 6: Output

- One-page client review summary (Word or PDF)
- Performance table with benchmarks
- Allocation pie chart (current vs. target)
- Recommended action items
- Meeting agenda

## Important Notes

- Know your client before the meeting — review notes from last meeting
- Lead with what the client cares about, not what you want to talk about
- If performance was bad, address it directly — don't hide or spin
- Always end with clear action items and next steps with dates
- Document the meeting notes and any changes to the IPS
- Compliance: ensure all materials are compliant with firm policies and regulatory requirements
