# Release Notes — 2026-03-05

This document captures the current repository diff set before publish.

## Platform and Data Plane

- Replaced `servers/health-records-mcp` with `servers/health-graph-mcp`.
- Added health-graph schema/migrations/tests/scripts for assertion-first genome/clinical modeling.
- Updated Postgres initialization and backup scripts for the health-graph service:
  - `services/personal-db/init-databases.sh`
  - `services/backup-personal.sh`
- Updated OCI/local deploy scripts for current server topology:
  - `servers/oci-personal-provision/deploy.sh`
  - `servers/oci-personal-provision/deploy-local.sh`

## Wellness Connectors

- Added/expanded `servers/wger-mcp/server.py` with FitBod CSV tooling:
  - parse, mapping preview, import, alias persistence, import status.
- Added `servers/peloton-mcp` with:
  - OAuth PKCE bootstrap helpers,
  - refresh-token auth with persisted token-store support,
  - diagnostics/workout detail/performance/class metadata tools,
  - usefulness gate probe.
- Added persistent fitbod and apple-health data artifacts under `data/`.

## Wellness Advisor Persona and Skills

- Updated wellness advisor configuration and guidance:
  - `agent-configs/wellness-advisor/AGENTS.md`
  - `agent-configs/wellness-advisor/.codex/config.toml.example`
- Added operational scripts:
  - `agent-configs/wellness-advisor/scripts/compare_workout_granularity.py`
  - `agent-configs/wellness-advisor/scripts/open_wearables_pilot_check.py`
  - `agent-configs/wellness-advisor/scripts/OPEN_WEARABLES_PILOT.md`
- Updated wellness skills:
  - `skills/personas/wellness-advisor/health-dashboard/SKILL.md`
  - `skills/personas/wellness-advisor/medical-records/SKILL.md`
  - `skills/personas/wellness-advisor/weekly-health/SKILL.md`

## Mail Worker / Scheduling

- Updated family office mail worker behavior and shared scheduling code:
  - `agents/family-office-mail-worker/src/main.py`
  - `agents/family-office-mail-worker/src/models.py`
  - `agents/lib/schedule_loader.py`
  - `agents/schedules.yaml`

## Validation Utilities

- Updated skill/tool reference validation script:
  - `scripts/verify_skill_tool_refs.py`

## Documentation Status

- MCP architecture docs updated for `health-graph-mcp` and wellness connector direction:
  - `docs/architecture/mcp-servers/README.md`
- Roadmap updated with Apple Health ingestion automation stream:
  - `ROADMAP.md`
