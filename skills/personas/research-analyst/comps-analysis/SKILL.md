---
name: comps-analysis
description: Public comparable company valuation — peer selection, multiple derivation, and market-based valuation bands.
user-invocable: true
---

# /comps-analysis — Comparable Company Valuation

Produce a market-based valuation band using public comparable companies.

## MCP Tool Map

- Company fundamentals: `sec-edgar.sec_edgar_company`, `sec-edgar.sec_edgar_financial`
- Disclosure context: `sec-edgar.sec_edgar_filing`
- Market data: `market-intel-direct.get_market_snapshot`
- Illiquid asset context: `finance-graph.list_assets`, `finance-graph.list_valuation_observations`

## Workflow

### Step 1: Define Subject

- Identify the target company or asset to value.
- Capture key operating metrics: revenue, EBITDA, net income, growth rate, margins.

### Step 2: Peer Selection

- Select 5-10 public comparables based on sector, size, growth profile, and business model.
- Pull financial data from SEC filings for each peer.
- Document selection rationale and any exclusions.

### Step 3: Multiple Derivation

- Compute relevant trading multiples: EV/Revenue, EV/EBITDA, P/E, EV/FCF.
- Calculate median, mean, 25th, and 75th percentile for each multiple.
- Adjust for growth differential, margin differential, and scale.

### Step 4: Valuation Band

- Apply selected multiples to subject financials.
- Produce low/base/high valuation range.
- Apply applicable discounts (illiquidity, minority, key-person) where justified.

### Step 5: Output

- Peer set with key financials.
- Multiple summary table.
- Implied valuation range with methodology notes.
- Key assumptions and data-quality caveats.
