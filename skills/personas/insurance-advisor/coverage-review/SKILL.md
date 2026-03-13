# Coverage Review

## Purpose
Analyze coverage adequacy across all policy types against current asset base, liability exposure, and life events.

## Workflow
1. Load current policy inventory (via `policy-inventory` skill or direct Paperless query)
2. Pull asset values from finance-graph (real estate, vehicles, valuables, net worth)
3. Pull liability data from finance-graph (mortgages, loans)
4. Evaluate coverage gaps:
   - Property: replacement cost vs dwelling coverage
   - Auto: liability limits vs net worth exposure
   - Umbrella: total underlying + umbrella vs litigation risk threshold
   - Life: coverage vs income replacement needs and estate liquidity
   - Disability: benefit vs income percentage
5. Flag any assets without corresponding coverage
6. Compare limits against industry guidelines and net worth benchmarks

## Output Format
Gap analysis report with: Coverage Area | Current Limit | Recommended Minimum | Gap | Priority | Action

## Tool Dependencies
- `paperless.search_documents` — current policies
- `finance-graph.get_net_worth` — total net worth for sizing
- `finance-graph.list_assets` — asset details for coverage matching
- `finance-graph.list_liabilities` — liability exposure
- `actual-budget.budget` — premium budget context
