-- Make hydration sources idempotent and safe for nightly delta runs.
-- Apply with:
--   psql "$DATABASE_URL" -f migrations/20260305_hydration_idempotency.sql

BEGIN;

SET search_path TO health, public;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                subject_id,
                gene_symbol,
                source_name,
                COALESCE(source_diplotype, ''),
                COALESCE(recommendation_diplotype, '')
            ORDER BY id DESC
        ) AS rn
    FROM pgx_diplotypes
)
DELETE FROM pgx_diplotypes t
USING ranked r
WHERE t.id = r.id
  AND r.rn > 1;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                subject_id,
                gene_symbol,
                COALESCE(phenotype, ''),
                COALESCE(activity_score, ''),
                COALESCE(phenotype_source, '')
            ORDER BY id DESC
        ) AS rn
    FROM pgx_phenotypes
)
DELETE FROM pgx_phenotypes t
USING ranked r
WHERE t.id = r.id
  AND r.rn > 1;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                subject_id,
                COALESCE(gene_symbol, ''),
                COALESCE(drug_name, ''),
                source_name,
                COALESCE(source_record_id, ''),
                recommendation_text
            ORDER BY id DESC
        ) AS rn
    FROM pgx_recommendations
)
DELETE FROM pgx_recommendations t
USING ranked r
WHERE t.id = r.id
  AND r.rn > 1;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                COALESCE(variant_id, 0),
                COALESCE(gene_id, 0),
                source_name,
                COALESCE(source_record_id, ''),
                COALESCE(condition_name, ''),
                COALESCE(significance, '')
            ORDER BY id DESC
        ) AS rn
    FROM clinical_assertions
)
DELETE FROM clinical_assertions t
USING ranked r
WHERE t.id = r.id
  AND r.rn > 1;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                COALESCE(variant_id, 0),
                source_name,
                trait_name,
                COALESCE(study_id, ''),
                COALESCE(effect_allele, '')
            ORDER BY id DESC
        ) AS rn
    FROM trait_associations
)
DELETE FROM trait_associations t
USING ranked r
WHERE t.id = r.id
  AND r.rn > 1;

WITH ranked AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY
                literature_evidence_id,
                COALESCE(assertion_id, 0),
                COALESCE(variant_id, 0),
                COALESCE(trait_association_id, 0),
                COALESCE(notes, '')
            ORDER BY id DESC
        ) AS rn
    FROM evidence_links
)
DELETE FROM evidence_links t
USING ranked r
WHERE t.id = r.id
  AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_pgx_diplotypes_dedupe
    ON pgx_diplotypes(
        subject_id,
        gene_symbol,
        source_name,
        COALESCE(source_diplotype, ''),
        COALESCE(recommendation_diplotype, '')
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_pgx_phenotypes_dedupe
    ON pgx_phenotypes(
        subject_id,
        gene_symbol,
        COALESCE(phenotype, ''),
        COALESCE(activity_score, ''),
        COALESCE(phenotype_source, '')
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_pgx_recommendations_dedupe
    ON pgx_recommendations(
        subject_id,
        COALESCE(gene_symbol, ''),
        COALESCE(drug_name, ''),
        source_name,
        COALESCE(source_record_id, ''),
        recommendation_text
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_assertions_dedupe
    ON clinical_assertions(
        COALESCE(variant_id, 0),
        COALESCE(gene_id, 0),
        source_name,
        COALESCE(source_record_id, ''),
        COALESCE(condition_name, ''),
        COALESCE(significance, '')
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_trait_associations_dedupe
    ON trait_associations(
        COALESCE(variant_id, 0),
        source_name,
        trait_name,
        COALESCE(study_id, ''),
        COALESCE(effect_allele, '')
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_links_dedupe
    ON evidence_links(
        literature_evidence_id,
        COALESCE(assertion_id, 0),
        COALESCE(variant_id, 0),
        COALESCE(trait_association_id, 0),
        COALESCE(notes, '')
    );

COMMIT;
