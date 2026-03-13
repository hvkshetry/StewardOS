# Backtesting Patterns Reference

Practitioner-grade backtesting heuristics for the Investment Officer persona.
Use these rules to audit any backtest before acting on its signals.

---

## US Market Cost Model Rules

Accurate cost modeling is the single fastest way to kill a fake edge.
Always model **round-trip costs**, not just entry.

| Cost Component | Current Rule | Notes |
|---------------|-------------|-------|
| Equity commissions | $0 | Major brokers (Schwab, Fidelity, IBKR Lite). IBKR Pro charges tiered. |
| Options commissions | $0.65 / contract | Per-leg. Multi-leg strategies multiply quickly. |
| SEC fee (Section 31) | ~$8 per $1M of sell proceeds | Updated annually by the SEC; applies only to sells. |
| FINRA TAF | $0.000166 per share sold | Capped at $8.30 per trade. Applies only to sells. |
| Slippage (large-cap liquid) | 1 - 5 bps | S&P 500 constituents during regular hours. |
| Slippage (small-cap / illiquid) | 10 - 25 bps | Sub-$2B market cap, ADV < 500K shares. |

**Key discipline**: Run every backtest at 1x, 2x, and 3x cost assumptions.
If the strategy dies at 2x costs, the edge is too thin to trade live.

---

## Walk-Forward Methodology

### In-Sample / Out-of-Sample Splits

- **Standard split**: 70% in-sample (IS) / 30% out-of-sample (OOS).
- **Rolling window**: Fixed-length IS window slides forward; OOS is the next period.
- **Anchored walk-forward**: IS start date is fixed; IS window grows over time. Better for regime-stable strategies.

### Regime Awareness

Test across distinct market regimes — do not average away regime effects:

- **Bull**: 2013-2015, 2017, 2019, 2021
- **Bear**: 2008-2009, Feb-Mar 2020, 2022
- **Sideways / choppy**: 2011, 2015 Q3-Q4, 2018

A strategy that only works in one regime is a regime bet, not an edge.

### Bias Prevention

| Bias | Prevention |
|------|-----------|
| Look-ahead bias | No future data in feature engineering. Use point-in-time data only. |
| Survivorship bias | Use point-in-time constituent lists (e.g., historical S&P 500 membership). |
| Selection bias | Define the strategy universe rules before running the backtest. |
| Data-snooping bias | Reserve a final holdout period that is never touched during development. |

---

## Robustness Testing Checklist

Run every candidate strategy through this full checklist before promotion:

### Monte Carlo Simulation
- Bootstrap returns: resample daily/trade returns with replacement (1,000+ iterations).
- Reshuffle trade sequence: randomize trade ordering to test path dependency.
- Report: median, 5th, and 95th percentile equity curves.

### Parameter Sensitivity
- Vary each key parameter +/- 20% independently.
- Strategy must remain profitable across the full grid.
- If a 10% parameter shift flips the sign of returns, the strategy is curve-fit.

### Drawdown Analysis
- **Max drawdown**: peak-to-trough percentage loss.
- **Drawdown duration**: calendar days from peak to recovery.
- **Recovery time**: days from trough to new high.
- Report all three. A shallow but multi-year drawdown can be worse than a deep but fast one.

### Transaction Cost Sensitivity
- Run at 1x, 2x, and 3x modeled costs.
- If Sharpe drops below 0.5 at 2x costs, the edge is insufficient.

### Correlation Regime Breaks
- Test during correlation spike periods (2008 Q4, 2020 March, 2022 Q1).
- Diversification-dependent strategies often fail when correlations go to 1.

### Out-of-Sample Degradation Tracking
- Compute IS Sharpe and OOS Sharpe separately.
- Track the ratio: OOS Sharpe / IS Sharpe.
- Expect ~50% decay. If decay exceeds 60%, suspect overfitting.

---

## Strategy Validation Gates

A strategy must pass **all** gates before paper trading:

| Gate | Threshold | Rationale |
|------|-----------|-----------|
| Minimum trade count | > 100 trades | Below this, statistical significance is unreliable. |
| IS Sharpe ratio | > 1.5 | Must be high enough to survive OOS decay. |
| OOS Sharpe ratio | > 0.8 | Practical lower bound for a tradeable edge. |
| Max drawdown survival | Must survive 2008-2009 and March 2020 | If it blows up in known crises, it will blow up in unknown ones. |
| Win rate context | Meaningless without payoff ratio | A 30% win rate with 5:1 payoff is excellent. An 80% win rate with 0.2:1 payoff is ruin. |
| Cost robustness | Profitable at 2x costs | Protects against slippage model error. |
| Parameter stability | Profitable across +/- 20% grid | Protects against curve fitting. |

### Promotion Ladder

1. **Backtest passes all gates** — move to paper trading.
2. **Paper trading confirms OOS behavior** (30-60 days) — move to small live allocation.
3. **Small live allocation confirms execution quality** (60-90 days) — scale to target size.

Never skip a rung.
