BEGIN;

CREATE SCHEMA IF NOT EXISTS tax;
SET search_path TO tax;

DROP TABLE IF EXISTS retirement_elections CASCADE;
DROP TABLE IF EXISTS compensation_strategies CASCADE;
DROP TABLE IF EXISTS estimated_payment_plans CASCADE;
DROP TABLE IF EXISTS scenario_results CASCADE;
DROP TABLE IF EXISTS scenario_runs CASCADE;
DROP TABLE IF EXISTS business_profiles CASCADE;
DROP TABLE IF EXISTS return_facts CASCADE;

CREATE TABLE IF NOT EXISTS return_fact_documents (
    document_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    tax_year INT NOT NULL,
    source_name TEXT,
    source_path TEXT,
    facts JSONB NOT NULL,
    support_assessment JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exact_computations (
    run_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    tax_year INT NOT NULL,
    facts JSONB NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS safe_harbor_plans (
    plan_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    tax_year INT NOT NULL,
    facts JSONB NOT NULL,
    plan JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_return_fact_documents_entity_year
    ON return_fact_documents (entity_type, tax_year, ingested_at DESC);
CREATE INDEX IF NOT EXISTS idx_exact_computations_entity_year
    ON exact_computations (entity_type, tax_year, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_safe_harbor_plans_entity_year
    ON safe_harbor_plans (entity_type, tax_year, created_at DESC);

COMMIT;
