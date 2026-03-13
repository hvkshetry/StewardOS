BEGIN;

CREATE SCHEMA IF NOT EXISTS tax;
SET search_path TO tax;

CREATE TABLE IF NOT EXISTS authority_bundles (
    bundle_version TEXT PRIMARY KEY,
    tax_year INT NOT NULL,
    jurisdictions JSONB NOT NULL,
    federal_individual_kernel TEXT NOT NULL,
    federal_fiduciary_kernel TEXT NOT NULL,
    massachusetts_kernel TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO authority_bundles(
    bundle_version,
    tax_year,
    jurisdictions,
    federal_individual_kernel,
    federal_fiduciary_kernel,
    massachusetts_kernel
)
VALUES (
    'us_ma_2026_v1',
    2026,
    '["US","MA"]'::jsonb,
    'taxcalc_2026',
    'builtin_2026_fiduciary_kernel',
    'builtin_2026_ma_kernel'
)
ON CONFLICT (bundle_version) DO NOTHING;

CREATE TABLE IF NOT EXISTS prior_year_return_facts (
    document_id TEXT PRIMARY KEY REFERENCES return_fact_documents(document_id) ON DELETE CASCADE,
    total_tax NUMERIC(18,2) NOT NULL,
    adjusted_gross_income NUMERIC(18,2) NOT NULL,
    massachusetts_total_tax NUMERIC(18,2),
    full_year_return BOOLEAN NOT NULL DEFAULT TRUE,
    filed BOOLEAN NOT NULL DEFAULT TRUE,
    first_year_massachusetts_fiduciary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payment_ledger_events (
    event_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES return_fact_documents(document_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('estimated_payment', 'withholding')),
    payment_date DATE NOT NULL,
    jurisdiction TEXT NOT NULL CHECK (jurisdiction IN ('US', 'MA')),
    amount NUMERIC(18,2) NOT NULL CHECK (amount >= 0),
    treat_as_ratable BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payment_ledger_events_document
    ON payment_ledger_events (document_id, event_type, payment_date);

CREATE TABLE IF NOT EXISTS exact_runs (
    run_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    tax_year INT NOT NULL,
    authority_bundle_version TEXT NOT NULL REFERENCES authority_bundles(bundle_version),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exact_results (
    run_id TEXT PRIMARY KEY REFERENCES exact_runs(run_id) ON DELETE CASCADE,
    facts JSONB NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_exact_runs_entity_year
    ON exact_runs (entity_type, tax_year, created_at DESC);

ALTER TABLE safe_harbor_plans
    ADD COLUMN IF NOT EXISTS authority_bundle_version TEXT;

UPDATE safe_harbor_plans
SET authority_bundle_version = 'us_ma_2026_v1'
WHERE authority_bundle_version IS NULL;

ALTER TABLE safe_harbor_plans
    DROP CONSTRAINT IF EXISTS safe_harbor_plans_authority_bundle_version_fk;

ALTER TABLE safe_harbor_plans
    ADD CONSTRAINT safe_harbor_plans_authority_bundle_version_fk
    FOREIGN KEY (authority_bundle_version)
    REFERENCES authority_bundles(bundle_version);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'tax'
          AND table_name = 'safe_harbor_plans'
          AND column_name = 'authority_bundle_version'
    ) THEN
        ALTER TABLE safe_harbor_plans
            ALTER COLUMN authority_bundle_version SET NOT NULL;
    END IF;
END
$$;

DO $$
BEGIN
    IF to_regclass('tax.exact_computations') IS NOT NULL THEN
        INSERT INTO exact_runs(run_id, tool_name, entity_type, tax_year, authority_bundle_version, created_at)
        SELECT run_id, tool_name, entity_type, tax_year, 'us_ma_2026_v1', created_at
        FROM exact_computations
        ON CONFLICT (run_id) DO NOTHING;

        INSERT INTO exact_results(run_id, facts, result, created_at)
        SELECT run_id, facts, result, created_at
        FROM exact_computations
        ON CONFLICT (run_id) DO NOTHING;

        DROP TABLE exact_computations;
    END IF;
END
$$;

COMMIT;
