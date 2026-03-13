# Institutional Equity Research Report Template

8-section report structure mapped to the Investment Officer's MCP tool ecosystem.
Each section specifies page budget, content requirements, and canonical data sources.

---

## 1. Investment Summary (1 page)

**Purpose**: Executive-level decision brief. A reader should be able to act on this page alone.

### Required Elements

- **Recommendation**: Buy / Hold / Sell
- **Price target**: 12-month base case with upside/downside range
- **Time horizon**: Explicit (e.g., "12-month", "through cycle")
- **Key thesis points**: 3-5 bullets, each one sentence
- **Risk/reward skew**: Quantified (e.g., "+35% to target / -15% to downside case")
- **Catalyst timeline**: Next 1-3 identifiable catalysts with dates

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| Current holdings & cost basis | `ghostfolio.portfolio` | Position context, existing exposure check |
| Portfolio-level state | `portfolio-analytics.get_condensed_portfolio_state` | Concentration, sector weight, portfolio fit |

---

## 2. Company Overview (0.5 page)

**Purpose**: Orient the reader on what the company does and who runs it.

### Required Elements

- Business description: what it sells, to whom, in which geographies
- Segment breakdown: revenue and operating income by segment
- End markets served and cyclicality profile
- Management quality assessment: tenure, capital allocation track record, insider ownership

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| Company metadata & filings index | `sec-edgar.sec_edgar_company` | CIK lookup, filing history, SIC code |

---

## 3. Industry & Competitive Position (1 page)

**Purpose**: Establish the structural attractiveness of the industry and the company's defensibility within it.

### Required Elements

- **Market size and growth**: TAM/SAM/SOM with growth rates
- **Competitive moat assessment** — score each:
  - Brand power
  - Network effects
  - Switching costs
  - Cost advantages / economies of scale
  - Intellectual property / regulatory barriers
- **Market share trends**: directional over 3-5 years
- **Competitive landscape**: key competitors, relative positioning

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| 10-K industry discussion | `sec-edgar.sec_edgar_filing` | Extract industry section from annual report |
| Market news & trends | `market-intel-direct.search_market_news` | Recent industry developments, competitor moves |

---

## 4. Financial Analysis (1.5 pages)

**Purpose**: Deep dive into the company's financial performance, trajectory, and quality.

### Required Elements

- **Revenue decomposition**: by segment, geography, organic vs acquired
- **Growth drivers**: volume vs price, new products, market expansion
- **Margin analysis**: gross, operating, net — levels and trajectory
- **Capital allocation track record**:
  - R&D intensity and productivity
  - Capex (maintenance vs growth)
  - M&A history and returns
  - Buyback effectiveness (accretive vs dilution offset)
  - Dividend policy and sustainability
- **Balance sheet quality**: net debt / EBITDA, interest coverage, maturity schedule
- **Cash flow quality**: FCF conversion, working capital trends, accruals ratio

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| Financial statements (IS, BS, CF) | `sec-edgar.sec_edgar_financial` | Multi-year financials extraction |
| Ratio computation | ratio_calculator.py script | Automated ratio computation from raw financials |

---

## 5. Valuation (1 page)

**Purpose**: Determine whether the current price offers an adequate margin of safety.

### Required Elements

- **Relative valuation**:
  - P/E, EV/EBITDA, P/FCF vs peer group
  - Current multiples vs own 5-year history
  - Premium/discount justification
- **Intrinsic valuation (DCF)**:
  - Base case: management guidance / consensus assumptions
  - Bull case: upside scenario with explicit assumption changes
  - Bear case: downside scenario with explicit assumption changes
  - Key sensitivities: WACC and terminal growth rate matrix
- **Implied expectations**: what growth rate is the market pricing in?

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| Financial data for model inputs | `sec-edgar.sec_edgar_financial` | Revenue, margins, capex, D&A for DCF inputs |
| DCF model execution | dcf_valuation.py script | Standardized DCF with scenario analysis |

---

## 6. Risk Factors (0.5 page)

**Purpose**: Enumerate the risks that could break the thesis, ranked by probability and impact.

### Required Elements

- **Company-specific risks**: execution, key person, customer concentration, technology disruption
- **Industry / macro risks**: cyclicality, input costs, demand destruction
- **Regulatory / policy risks**: pending legislation, regulatory actions, tax policy changes
- **Mitigants**: for each major risk, note any natural hedges or mitigating factors

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| Risk factors section | `sec-edgar.sec_edgar_filing` | Extract Item 1A from 10-K |
| Policy / legislative risk | `policy-events.get_recent_bills` | Pending legislation affecting the company or sector |

---

## 7. ESG & Governance (0.5 page)

**Purpose**: Assess material ESG factors and governance quality that affect long-term value.

### Required Elements

- **Board independence and structure**: % independent, dual class shares, staggered board
- **Executive compensation alignment**: pay-for-performance, metrics used, clawback provisions
- **Material ESG factors**: only factors with demonstrable financial materiality for this industry
- **Insider ownership and transactions**: recent buys/sells, ownership level alignment

### MCP Data Sources

| Source | Tool | Usage |
|--------|------|-------|
| Insider transactions | `sec-edgar.sec_edgar_insider` | Recent insider buys/sells, Section 16 filings |
| Proxy statement / DEF 14A | `sec-edgar.sec_edgar_filing` | Governance structure, compensation details |

---

## 8. Appendix: Data Tables (1 page)

**Purpose**: Supporting data tables for reference and model audit.

### Required Tables

#### 5-Year Financial Summary
| Metric | FY-4 | FY-3 | FY-2 | FY-1 | FY0 |
|--------|------|------|------|------|-----|
| Revenue | | | | | |
| Revenue growth % | | | | | |
| Gross margin % | | | | | |
| Operating margin % | | | | | |
| Net income | | | | | |
| EPS (diluted) | | | | | |
| FCF | | | | | |
| Net debt / EBITDA | | | | | |
| ROIC | | | | | |
| Dividend per share | | | | | |

#### Comparable Company Table
| Company | Ticker | Mkt Cap | P/E | EV/EBITDA | P/FCF | Rev Growth | Op Margin |
|---------|--------|---------|-----|-----------|-------|------------|-----------|
| Subject | | | | | | | |
| Peer 1 | | | | | | | |
| Peer 2 | | | | | | | |
| Peer 3 | | | | | | | |
| Median | | | | | | | |

#### DCF Sensitivity Matrix (Implied Share Price)
| | WACC -1% | WACC Base | WACC +1% |
|---|----------|-----------|----------|
| Terminal growth +0.5% | | | |
| Terminal growth base | | | |
| Terminal growth -0.5% | | | |

#### Insider Transaction Summary (Last 12 Months)
| Date | Insider | Title | Type | Shares | Price | Value |
|------|---------|-------|------|--------|-------|-------|
| | | | | | | |

---

## Usage Notes

- Fill every section. If data is unavailable, state "Data not available" with the reason.
- All financial figures in USD millions unless otherwise noted.
- Price target must be derivable from the valuation section; no unexplained targets.
- Tag each data point with its MCP source for audit trail.
- Update frequency: refresh when a material event occurs or quarterly at minimum.
