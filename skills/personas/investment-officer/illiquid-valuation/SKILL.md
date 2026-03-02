---
name: illiquid-valuation
description: Orchestrate comps, DCF, returns, and unit-economics methods to value private and illiquid holdings with explicit confidence bands.
user-invocable: true
---

# /illiquid-valuation

Produce a decision-grade valuation range for private or illiquid assets.

## MCP Tool Map

- Illiquid source-of-truth context: `finance-graph.list_assets`, `finance-graph.list_valuation_observations`, `finance-graph.get_ownership_graph`
- Valuation write path: `finance-graph.upsert_asset`, `finance-graph.set_manual_comp_valuation`, `finance-graph.record_valuation_observation`, `finance-graph.refresh_us_property_valuation`
- Estate-planning boundary: succession/legal records live in `estate-planning`; valuation/statement facts remain finance-only in `finance-graph`
- Holdings context: `ghostfolio.account`, `ghostfolio.portfolio`
- Comp and disclosure context: `sec-edgar.sec_edgar_company`, `sec-edgar.sec_edgar_financial`, `sec-edgar.sec_edgar_filing`
- Macro/rates context: `market-intel-direct.get_market_snapshot`, `market-intel-direct.get_fred_series`
- Tax impact context: `household-tax.compare_tax_scenarios`
- Policy context where material: `policy-events.get_federal_rules`

## Workflow

### Step 1: Define Asset and Evidence Set

- Identify stake type, ownership percent, rights, restrictions, and liquidity profile.
- Capture latest financial package and operating KPIs.
- For asset creation/updates, use normalized taxonomy (`asset_class_code`, `asset_subclass_code`) and explicit `jurisdiction_code` + `valuation_currency`.
- Use RentCast automation only for US properties; use manual comps/marks for India properties.

### Step 2: Multi-Method Valuation

- Run `comps-analysis` method for market-based valuation band.
- Run `dcf-model` method for intrinsic valuation band.
- Run `returns-analysis` for investor-outcome consistency check.
- Run `unit-economics` where recurring/contracted revenue is material.

### Step 3: Synthesize Range

- Combine method outputs into low/base/high range.
- Apply liquidity, governance, concentration, and key-person discounts where justified.
- Record assumptions explicitly.

### Step 4: Portfolio and Tax Implications

- Evaluate impact on total household concentration and risk posture.
- Show high-level after-tax implications for hold vs partial liquidity events.

### Step 5: Output

- Valuation range with method weights.
- Confidence score and data-quality caveats.
- Top sensitivities and next data requests.
