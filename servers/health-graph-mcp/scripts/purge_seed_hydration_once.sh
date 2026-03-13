#!/usr/bin/env bash
# One-time cleanup for legacy hydration seed rows.
# Usage:
#   DATABASE_URL=postgresql://... ./scripts/purge_seed_hydration_once.sh
set -euo pipefail

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is required" >&2
  exit 1
fi

SEED_PATTERN="${SEED_PATTERN:-%seed_20260305%}"

psql "${DATABASE_URL}" -v ON_ERROR_STOP=1 <<SQL
BEGIN;
SET search_path TO health, public;

DROP TABLE IF EXISTS _seed_sources;
CREATE TEMP TABLE _seed_sources AS
SELECT DISTINCT source_name
FROM ingestion_runs
WHERE source_name ILIKE '${SEED_PATTERN}'
   OR source_name ILIKE '%smoke%'
   OR source_name ILIKE '%placeholder%';

DELETE FROM evidence_links el
USING literature_evidence le
WHERE el.literature_evidence_id = le.id
  AND le.source_name IN (SELECT source_name FROM _seed_sources);

DELETE FROM literature_evidence
WHERE source_name IN (SELECT source_name FROM _seed_sources);

DELETE FROM trait_associations
WHERE source_name IN (SELECT source_name FROM _seed_sources);

DELETE FROM clinical_assertions
WHERE source_name IN (SELECT source_name FROM _seed_sources);

DELETE FROM pgx_recommendations
WHERE source_name IN (SELECT source_name FROM _seed_sources);

DELETE FROM pgx_diplotypes
WHERE source_name IN (SELECT source_name FROM _seed_sources);

DELETE FROM pgx_phenotypes
WHERE phenotype_source IN (SELECT source_name FROM _seed_sources);

DELETE FROM ingestion_runs
WHERE source_name IN (SELECT source_name FROM _seed_sources);

COMMIT;
SQL

echo "Seed hydration cleanup complete for pattern: ${SEED_PATTERN}"
