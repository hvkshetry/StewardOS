---
description: Full portfolio rebalancing with tax-loss harvesting and ES-constrained optimization
allowed-tools: Read, Write, mcp__portfolio-state-server__import_broker_csv, mcp__portfolio-state-server__get_portfolio_state, mcp__portfolio-state-server__simulate_sale, mcp__portfolio-state-server__get_tax_loss_harvesting_opportunities, mcp__portfolio-optimization-server__optimize_portfolio_advanced, mcp__risk-server__analyze_portfolio_risk, mcp__tax-server__calculate_comprehensive_tax, mcp__tax-optimization-server__find_tax_loss_harvesting_pairs, mcp__openbb-curated__equity_price_historical, mcp__openbb-curated__equity_fundamental_metrics, mcp__openbb-curated__economy_cpi, mcp__openbb-curated__fixedincome_government_yield_curve, mcp__policy-events-service__get_recent_bills
argument-hint: <target_allocation> (e.g., "80% equity / 20% bonds")
---

Rebalance my portfolio with professional-grade optimization, tax efficiency, and mandatory ES validation.

## User Request
Target allocation: {target_allocation from user}

## Comprehensive Rebalancing Workflow

### Stage 1: Import & Context (Parallel)
1. **Import Portfolio**
   - Use `@portfolio-manager` to import current positions
   - Read Vanguard and UBS CSVs
   - Get complete portfolio state with tax lots

2. **Market Analysis** (run in parallel)
   - `@macro-analyst`: Economic outlook, rates, inflation
   - `@equity-analyst`: Equity market valuations, earnings outlook
   - `@fixed-income-analyst`: Yield curve, duration strategy

### Stage 2: Optimization Candidates
Use `@portfolio-manager` to generate 2-3 optimization candidates:
- **HRP (Hierarchical Risk Parity)**: Risk-balanced allocation
- **Max Sharpe**: Return-optimized with ES constraint
- **Risk Parity**: Equal risk contribution

**BINDING CONSTRAINT**: All candidates MUST have ES < 2.5% at 97.5% confidence

### Stage 3: Risk Validation
For EACH candidate, use `@risk-analyst` to:
- Calculate ES at 97.5% confidence (MUST be < 2.5%)
- Run stress tests (2008 crisis, COVID crash, tech selloff)
- Check concentration limits (20% max individual stocks)
- Verify lookthrough analysis for fund holdings

**HALT if ANY candidate has ES > 2.5%**

### Stage 4: Tax Analysis
For EACH candidate, use `@tax-advisor` to:
- Calculate realized gains/losses with FIFO lot selection
- Identify tax-loss harvesting opportunities
- Estimate tax liability (federal + state)
- Check wash sale rules (31-day lookback)

### Stage 5: Policy Gates (MANDATORY)
Use `@gate-validator` to validate ALL candidates:

**Primary Gates (HALT if failed):**
- **ES Gate**: ES @ 97.5% ≤ 2.5% (BINDING - check `executive_summary.halt_required`)
- **Tax Gate**: Tax reconciliation, wash sales, municipal bonds
- **Compliance Gate**: Account minimums, pattern day trading

**Secondary Gates (Warning if failed):**
- **Realism Gate**: Sharpe < 3.0, expected return < 50%
- **Credibility Gate**: Multi-source data validation

**Validation Process:**
1. Extract `executive_summary.es_975_1day` from risk analysis
2. Extract `executive_summary.halt_required` flag
3. If `halt_required == true`, IMMEDIATELY HALT and alert user
4. If ES > 2.5%, HALT even if flag is false (defensive check)
5. Validate tax reconciliation against portfolio state
6. Check compliance constraints
7. Document all gate results in `gate_validation.json`

**This is MANDATORY Round-2 validation for all portfolio revisions**

### Stage 6: Final Selection & Trade List
1. Compare all candidates side-by-side
2. Select best candidate considering:
   - ES level (lower is better)
   - Tax efficiency (after-tax return)
   - Turnover (minimize transaction costs)
   - Rebalancing frequency (avoid over-trading)

3. Generate detailed trade list with:
   - Buy/sell orders
   - Lot-specific sales (FIFO)
   - Tax implications per trade
   - Expected ES after execution

### Stage 7: IC Memo
Use `@ic-memo-generator` to create Investment Committee memo with:
- Executive summary
- Market context and rationale
- Optimization methodology
- Risk analysis and stress tests
- Tax implications
- Recommended trades
- ES verification (< 2.5%)

## Critical Constraints

- **ES ≤ 2.5%** at 97.5% confidence (BINDING - HALT if exceeded)
- **Concentration**: 20% max individual stocks, funds exempt
- **Tool-first data**: All metrics from MCP tools with provenance
- **Round-2 Gate**: Mandatory validation for all revisions
- **Tax reconciliation**: Single source of truth, FIFO lots

## Output

Save all artifacts to session directory:
- `portfolio_snapshot.json`
- `macro_context.json`, `equity_analysis.json`, `fixed_income_analysis.json`
- `optimization_candidate_1.json`, `optimization_candidate_2.json`, ...
- `risk_report_1.json`, `risk_report_2.json`, ...
- `tax_impact_1.json`, `tax_impact_2.json`, ...
- `gate_validation.json`
- `trade_list.json`
- `IC_Memo.md`

**HALT PROTOCOL**: If ES > 2.5% at ANY stage, stop immediately and alert user.
