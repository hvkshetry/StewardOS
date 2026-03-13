---
name: practitioner-heuristics
description: >
  Practitioner heuristic overlay for portfolio review. Implements hard gates
  (illiquidity ceiling, employer concentration) and advisory layers (ruin
  scenario, barbell classification, regime exposure, market temperature,
  position valuations). Called as a sub-skill from portfolio-review after
  the quantitative risk check (ES/VaR). Disagreement between the ES layer
  and heuristic layers is the most valuable signal.
user-invocable: false
---

# Practitioner Heuristic Overlay

This skill adds the second risk lens alongside ES. It does two things:

1. enforce hard gates before advisory discussion
2. provide the heuristic context needed to sequence corrective actions

It should not replace the quantitative engine. ES remains binding.

## Architecture

### Hard gates

These gates block action classes:

| Gate | Threshold | Action |
|------|-----------|--------|
| ES limit | ES(97.5%) > 2.5% | Block new risk additions |
| Illiquidity ceiling | T2+T3 illiquid > 25% NW | Block new illiquid commitments |
| Employer concentration | Employer-linked liquid > 15% | Block incremental employer-linked risk |

### Advisory layers

These shape posture and the corrective path:

- ruin scenarios
- barbell posture
- regime concentration
- market temperature
- concentrated-position valuation context

## Mapping Tables

### Liquidity tier classification

| Tier | Label | Examples |
|------|-------|---------|
| T0 | Cash / risk-free | USD, VMFXX, SPAXX, SWVXX, FDRXX, SHV, BIL, SGOV, USFR, TFLO |
| T1 | Daily liquid | VTI, VXUS, VOO, SPY, QQQ, BND, AGG, TLT, GLD, GLDM |
| T2 | Semi-liquid | REITs, BDCs, interval funds |
| T3 | Illiquid | PE, VC, real estate, private credit |

### Barbell classification

| Bucket | Label | Examples |
|--------|-------|----------|
| Hyper-safe | Risk-free floor | USD, CASH, money-market funds, T-bills |
| Convex | Tail protection | GLDM, GLD, IAU, CAOS, TLT, DBMF, KMLM, approved long-vol structures |
| Fragile middle | Linear / concave payoff | broad beta, PE, individual equities, most credit, most real estate |

### Convex instrument menu

Treat this as governed input to `market-intel-direct.rank_convex_candidates`, not as an auto-prescription list.

Approved ranking universe:

- `GLDM`, `IAU`
- `DBMF`, `KMLM`
- `CAOS`
- `TLT` when regime-appropriate
- `SPY` put-spread templates when options capability permits

Avoid:

- `VXX`, `VIXY`
- `TAIL`
- `CYA`
- buffer ETFs presented as convex substitutes

## Execution Workflow

### Step 1: Run hard gates first

#### ES gate

- If `portfolio-analytics.analyze_portfolio_risk` returns `status == "critical"` or the illiquid overlay pushes adjusted ES above `2.5%`, fail the gate.

#### Illiquidity gate

- Use `finance-graph.get_net_worth` plus Ghostfolio liquid net worth.
- If illiquid share of household net worth is above `25%`, fail the gate.

#### Employer concentration gate

- Use `equity_comp` accounts plus any same-ticker holdings elsewhere.
- If employer-linked liquid exposure exceeds `15%`, fail the gate.

When a hard gate fails, say so plainly before advisory layers.

### Step 2: Run advisory layers

#### Ruin scenario

- Run `portfolio-analytics.compute_ruin_scenario`
- Show the full stress table, not only one scenario

#### Barbell posture

- Run `portfolio-analytics.classify_barbell_buckets`
- Report:
  - hyper-safe %
  - convex %
  - fragile-middle %
  - safe gap
  - convex gap
  - fragile excess

When convex is short, feed the gap into `market-intel-direct.rank_convex_candidates`.

#### Regime map

- Use the regime table plus macro inputs from `market-intel-direct.get_fred_series`
- Flag material underexposure to key regimes

#### Market temperature

- Run `market-intel-direct.get_shiller_cape`
- Run `market-intel-direct.compute_market_temperature`
- Only present a full score when `status == "complete"`
- If temperature is incomplete, report the missing components, not a faux-complete score

#### Concentrated-position valuation context

- Use `sec-edgar` and `market-intel-direct.get_symbol_history` for the top concentrated non-index names
- If data is unavailable, report the gap

## Corrective-Action Guidance

This skill should not stop at flagging a barbell problem.

When these thresholds breach:

- hyper-safe below `15%`
- convex below `10%`
- fragile-middle above `70%`

the output should say what the gap means and pass the notional gap to the `rebalance` workflow.

Convex guidance rules:

- `TLT` is conditional, not default
- inflationary or stagflationary setups should usually favor gold / managed futures / tail-risk implementations over pure duration convexity
- deflationary or recessionary setups may favor `TLT` and options-based hedges more heavily
- no convex instrument should be recommended only because it is on the allowlist; use the ranking tool

## Output Contract

```markdown
### Hard Gates
| Gate | Status | Detail |
|------|--------|--------|
| ES < 2.5% | PASS/FAIL | ES = X.XX% |
| Illiquidity < 25% | PASS/FAIL | Illiquid = XX.X% of NW |
| Employer Concentration < 15% | PASS/FAIL | [Employer] = XX.X% of liquid |

### Practitioner Heuristic Overlay
| Layer | Signal | Posture | Key Finding |
|-------|--------|---------|-------------|
| Taleb (Ruin) | [scenarios] | [posture] | [stress summary] |
| Taleb (Barbell) | FRAGILE/OK | [posture] | [safe/convex/fragile + gaps] |
| Dalio (Regime) | [signal] | [posture] | [regime concentration] |
| Marks (Temperature) | [score or incomplete] | [posture] | [cycle context] |
| Buffett / Soros | [signal] | [posture] | [valuation/reflexive note] |
```

## Constraints

- Advisory only
- hard gates must be enforced
- do not fabricate missing data
- use the convex ranking tool for candidate selection
- do not present an anti-fragile menu as if it were already the recommendation
