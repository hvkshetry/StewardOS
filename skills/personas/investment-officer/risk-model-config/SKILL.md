---
name: risk-model-config
description: Invoke before analyze_portfolio_risk when the portfolio contains illiquid, private, or real estate holdings that lack yfinance market data. Queries finance-graph for asset metadata and valuation history, then assembles the illiquid_overrides parameter for portfolio-analytics risk analysis.
user-invocable: false
---

# risk-model-config — Illiquid Risk Overlay Configuration

This skill runs **before** `portfolio-analytics.analyze_portfolio_risk` when the portfolio contains illiquid or private holdings that lack yfinance market data.

## Purpose

The portfolio-analytics risk engine drops symbols without yfinance data and renormalizes weights, causing risk to be computed on only the liquid slice. This skill bridges the gap by:

1. Querying finance-graph for illiquid asset metadata (PE, real estate, private holdings)
2. Estimating volatility and equity correlation for each illiquid position
3. Assembling the `illiquid_overrides` parameter for `analyze_portfolio_risk`

## MCP Tool Map

- Asset metadata: `finance-graph.list_assets`
- Valuation history: `finance-graph.list_valuation_observations`
- Portfolio context (liquid weights): `portfolio-analytics.get_condensed_portfolio_state`
- Risk analysis target: `portfolio-analytics.analyze_portfolio_risk`

## Execution Workflow

### 1. Identify Illiquid Positions

Query finance-graph for positions that will not have yfinance data:

```
finance-graph.list_assets(asset_class_code="securities")
finance-graph.list_assets(asset_class_code="real_estate")
```

Filter to positions with `data_source="MANUAL"` or no yfinance-compatible ticker.

### 2. Gather Valuation History

For each illiquid position, check for valuation time series:

```
finance-graph.list_valuation_observations(asset_id=<id>)
```

If a position has >= 8 quarterly observations, compute realized annual volatility from the observation series.

### 3. Check Valuation Staleness

For each illiquid position, after querying `finance-graph.list_valuation_observations(asset_id=...)`:

- Compute `days_since_valuation = (today - most_recent_observation.valuation_date).days`
- Classify with asset-class-specific thresholds:

| Asset Class    | Current       | Stale Mark     | Very Stale Mark |
|----------------|---------------|----------------|-----------------|
| Real Estate    | < 365 days    | 365–730 days   | > 730 days      |
| Private Equity | < 180 days    | 180–365 days   | > 365 days      |
| Other Illiquid | < 180 days    | 180–365 days   | > 365 days      |

- Vol uplift: `stale_mark` → +5pp to annual_vol, `very_stale_mark` → +10pp
- Include in override: `"valuation_age_days": N, "mark_staleness": "stale_mark"` or `"very_stale_mark"`
- The risk engine passes these fields through to output and generates alerts for `very_stale_mark`

### 4. Apply Category Defaults

For positions without sufficient valuation history, use these defaults:

| Asset Category | Annual Vol | ρ (equity) | Liquidity Discount |
|----------------|-----------|------------|-------------------|
| Private Equity (US) | 30% | 0.65 | 15% |
| Private Equity (India) | 35% | 0.50 | 20% |
| Real Estate (US) | 12% | 0.30 | 10% |
| Real Estate (India) | 15% | 0.20 | 15% |
| Venture / Early Stage | 40% | 0.40 | 25% |

These are conservative estimates. Override with realized data when available.

### 5. Compute Position Weights

For each illiquid position, compute its weight relative to total portfolio value (including liquid positions). Use `portfolio-analytics.get_condensed_portfolio_state` or `ghostfolio.portfolio(operation="summary")` to obtain total portfolio value.

### 6. Assemble illiquid_overrides

Build the list of override dicts:

```json
[
  {
    "symbol": "PVTCO",
    "weight": 0.10,
    "annual_vol": 0.30,
    "rho_equity": 0.65,
    "liquidity_discount": 0.15,
    "valuation_age_days": 200,
    "mark_staleness": "stale_mark"
  }
]
```

The `valuation_age_days` and `mark_staleness` fields are optional. When present, the risk engine passes them through to the overlay output and generates alerts for `very_stale_mark` positions.

### 7. Pass to Risk Analysis (First Pass)

Call `portfolio-analytics.analyze_portfolio_risk` with the assembled overrides, passing through any scope parameters from the calling skill:

```
portfolio-analytics.analyze_portfolio_risk(
  risk_model="auto",
  illiquid_overrides=<assembled list>,
  include_fx_risk=true
)
```

### 8. Regime-Conditional Adjustments (Second Pass)

After the first `analyze_portfolio_risk` call, check `vol_regime.current_regime`:

| Regime     | ρ Multiplier      | Vol Adjustment (India PE)               | Action                            |
|------------|-------------------|-----------------------------------------|-----------------------------------|
| low/normal | 1.0×              | none                                    | Use base overrides                |
| elevated   | 1.25× (cap 0.95)  | max(USDINR, NIFTY) vol ratio if > 1.0   | Re-run with stressed overrides    |
| crisis     | 1.50× (cap 0.95)  | max(USDINR, NIFTY) vol ratio if > 1.0   | Re-run with stressed overrides    |

When regime is `elevated` or `crisis`:

1. Stress ρ: `stressed_rho = min(base_rho × multiplier, 0.95)`
2. For India PE positions, stress vol using market data:
   - `market-intel-direct.get_symbol_history(symbol="USDINR=X", range="3mo")` → compute `inr_ratio = std(last_21d) / std(full_63d)`
   - `market-intel-direct.get_symbol_history(symbol="^NSEI", range="3mo")` → compute `nifty_ratio = std(last_21d) / std(full_63d)`
   - `stressed_vol = base_vol × max(1.0, max(inr_ratio, nifty_ratio))`
3. Re-run `analyze_portfolio_risk(illiquid_overrides=stressed_overrides)` — second pass

When stressed, present both:
- **Base ES**: illiquid overlay with category defaults
- **Stressed ES**: illiquid overlay with regime-adjusted parameters

## Output

This skill does not produce user-facing output. Its output is the `illiquid_overrides` parameter (base and optionally stressed) passed to `analyze_portfolio_risk`. The risk tool's `illiquid_overlay` section in its response contains the overlay results.

## Constraints

- Never fabricate valuation data. If finance-graph has no data for a position, use category defaults and flag the assumption.
- The liquidity discount adjusts weight (valuation haircut), NOT variance.
- Cross-correlations between illiquid positions use a one-factor model (ρ_ij = ρ_i × ρ_j) unless the agent has explicit information to override.
- This skill is advisory — it configures the risk model but does not change portfolio positions.
