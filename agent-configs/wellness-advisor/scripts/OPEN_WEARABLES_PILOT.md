# Open-Wearables Pilot Runbook

## Goal
Evaluate whether open-wearables reduces Apple Health ingestion friction and adds useful detail beyond current Apple Health MCP + direct FitBod/Peloton sources.

## Inputs
- Repo: `/tmp/open-wearables`
- Apple export zip: `/tmp/export.zip`
- Current Apple Health target dir: `$STEWARDOS_ROOT/data/apple-health`

## Steps
1. Confirm repo health and Apple integration wiring:
`python $STEWARDOS_ROOT/agent-configs/wellness-advisor/scripts/open_wearables_pilot_check.py`

2. Validate current Apple ingestion baseline:
`python $STEWARDOS_ROOT/agent-configs/wellness-advisor/scripts/compare_workout_granularity.py`

3. Run open-wearables backend in an isolated environment (do not replace production stack yet).

4. Test Apple XML import path (`/api/v1/users/{user_id}/import/apple/xml/direct` or S3 flow).

5. Test auto-health-export endpoint path (`/api/v1/users/{user_id}/import/apple/auto-health-export`) using SDK token/API key flow.

6. Query open-wearables MCP workouts/activity/sleep tools and export representative output.

7. Compare against baseline for:
- Operator effort to keep data fresh
- FitBod and Peloton detail quality
- Reliability and maintenance overhead

## Decision Gate
Adopt/augment only if:
- Lower recurring operator effort than current export-zip workflow
- Equal or better signal quality for target coaching/recovery use cases
- Operational complexity is acceptable on home-server deployment model
