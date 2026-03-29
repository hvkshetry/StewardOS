# health-graph-mcp

Assertion-first health graph MCP server for genomics, PGx, lab trends, and insurance coverage intelligence.

## Core Principles

- Paperless is the document/OCR source of record.
- Postgres health graph is the assertion and recommendation source of truth.
- All user-facing recommendations are policy-gated by evidence tier and action class.
- Nutrigenomics and exercise-genomics remain `research_only` in phase 1.

## Environment

- `DATABASE_URL` (default: `postgresql://health:changeme@localhost:5434/stewardos_db`)
- `PAPERLESS_URL` (default: `http://localhost:8223`)
- `PAPERLESS_API_TOKEN`
- `OPEN_TARGETS_GRAPHQL_ENDPOINT` (default: `https://api.platform.opentargets.org/api/v4/graphql`)

## Run

```bash
uv run python server.py
```

## Hydration Model

- Nightly hydration should use `hydrate_subject_genome_knowledge(person_id=..., mode="delta")`.
- Runtime hydration is non-destructive and idempotent (no replace-seed mode).
- Legacy seed cleanup is script-only:
  `scripts/purge_seed_hydration_once.sh` (not exposed as an MCP tool).
