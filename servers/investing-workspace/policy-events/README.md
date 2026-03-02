# Policy Events MCP Server

The Policy Events MCP server provides bulk retrieval + detail retrieval of U.S. policy data so investment workflows can reason over legislative and regulatory changes.

## Why this server exists

Investment policy signals are often missed when overly strict prefilters are applied. This server intentionally exposes broad data, then lets higher-level analysis decide relevance.

## Design model

Two-stage pattern:

1. **Bulk retrieval** tools: gather broad candidate sets.
2. **Detail retrieval** tools: fetch full records for selected IDs.

## Key principles

- no opaque prefilter heuristics,
- fail loudly on missing upstream data,
- deterministic tool semantics,
- clear separation between retrieval and analysis.

## Tool groups

### Stage 1: bulk retrieval

- `get_recent_bills`
- `get_federal_rules`
- `get_upcoming_hearings`

### Stage 2: detail retrieval

- `get_bill_details`
- `get_rule_details`
- `get_hearing_details`

## Example workflow

1. Pull last 7–30 days of bills/rules/hearings.
2. Score relevance in analyst workflow.
3. Fetch full details only for shortlisted IDs.
4. Feed enriched context into memo/risk processes.

## Configuration

Required API keys (environment variables):

- `CONGRESS_API_KEY`
- `GOVINFO_API_KEY`

Optional tuning:

- request timeout,
- retry limits.

## Integration role in StewardOS

This server is intended to be consumed by investment-focused personas and workflows, not as a standalone thesis engine.
