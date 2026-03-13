# Policy Inventory

## Purpose
Build and maintain a comprehensive registry of all active insurance policies across the household.

## Workflow
1. Query Paperless for documents tagged `insurance` + `active-policy`
2. For each policy, extract: carrier, policy number, type, coverage limits, deductibles, premium amount, payment frequency, effective dates, named insureds
3. Cross-reference with finance-graph assets to verify insured property matches current holdings
4. Present organized inventory grouped by policy type (property, auto, umbrella, life, health, disability, specialty)

## Output Format
HTML table with columns: Policy Type | Carrier | Policy # | Coverage Limit | Deductible | Annual Premium | Effective Dates | Status

## Tool Dependencies
- `paperless.search_documents` — find insurance documents
- `paperless.get_document` — retrieve policy details
- `finance-graph.list_assets` — verify insured assets
- `estate-planning.list_entities` — verify named insureds against entity structure
