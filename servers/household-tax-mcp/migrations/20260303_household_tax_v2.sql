BEGIN;

CREATE SCHEMA IF NOT EXISTS tax;
SET search_path TO tax;

CREATE TABLE IF NOT EXISTS business_profiles (
    profile_id TEXT PRIMARY KEY,
    profile JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS return_facts (
    return_id TEXT PRIMARY KEY,
    year INT NOT NULL,
    entity_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    forms_detected JSONB NOT NULL,
    schedules_detected JSONB NOT NULL,
    jurisdictions_detected JSONB NOT NULL,
    manual_review_flags JSONB NOT NULL,
    extracted_text_hash TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenario_runs (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    objective TEXT NOT NULL,
    horizon_years INT NOT NULL,
    state TEXT NOT NULL,
    tax_year INT NOT NULL,
    active_jurisdictions JSONB NOT NULL,
    assumptions JSONB NOT NULL,
    inputs JSONB NOT NULL,
    recommended_strategy_id TEXT NOT NULL,
    estimated_payments_plan_id TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenario_results (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES scenario_runs(run_id) ON DELETE CASCADE,
    rank INT NOT NULL,
    strategy_id TEXT NOT NULL,
    label TEXT NOT NULL,
    annual_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    annual_financing_cost NUMERIC(18, 2) NOT NULL DEFAULT 0,
    annual_penalty NUMERIC(18, 2) NOT NULL DEFAULT 0,
    annual_after_tax_cash NUMERIC(18, 2) NOT NULL DEFAULT 0,
    ending_net_worth NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_economic_cost NUMERIC(18, 2) NOT NULL DEFAULT 0,
    payroll_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    se_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    qbi_deduction NUMERIC(18, 2) NOT NULL DEFAULT 0,
    qbi_tax_shield NUMERIC(18, 2) NOT NULL DEFAULT 0,
    components JSONB NOT NULL,
    tax_totals JSONB NOT NULL,
    qbi_effects JSONB NOT NULL,
    retirement_effects JSONB NOT NULL,
    cashflow_effects JSONB NOT NULL,
    estimated_payment_implications JSONB NOT NULL,
    trajectory JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS estimated_payment_plans (
    plan_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    plan JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS compensation_strategies (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES scenario_runs(run_id) ON DELETE CASCADE,
    strategy_id TEXT NOT NULL,
    business_structure TEXT NOT NULL,
    w2_compensation NUMERIC(18, 2) NOT NULL DEFAULT 0,
    distribution_income NUMERIC(18, 2) NOT NULL DEFAULT 0,
    guaranteed_payments NUMERIC(18, 2) NOT NULL DEFAULT 0,
    payroll_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    se_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    qbi_deduction NUMERIC(18, 2) NOT NULL DEFAULT 0,
    qbi_tax_shield NUMERIC(18, 2) NOT NULL DEFAULT 0,
    total_tax NUMERIC(18, 2) NOT NULL DEFAULT 0,
    annual_after_tax_cash NUMERIC(18, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retirement_elections (
    id BIGSERIAL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES scenario_runs(run_id) ON DELETE CASCADE,
    strategy_id TEXT NOT NULL,
    plan TEXT NOT NULL,
    contribution NUMERIC(18, 2) NOT NULL DEFAULT 0,
    tax_deferral_value NUMERIC(18, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_return_facts_year_entity ON return_facts(year, entity_type);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_scenario ON scenario_runs(scenario_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scenario_results_run_rank ON scenario_results(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_compensation_strategies_run ON compensation_strategies(run_id, strategy_id);
CREATE INDEX IF NOT EXISTS idx_retirement_elections_run ON retirement_elections(run_id, strategy_id);

COMMIT;
