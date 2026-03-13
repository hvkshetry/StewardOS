BEGIN;

CREATE SCHEMA IF NOT EXISTS finance;
SET search_path TO finance;

CREATE TABLE IF NOT EXISTS ips_target_profiles (
    id                      SERIAL PRIMARY KEY,
    profile_code            TEXT NOT NULL,
    name                    TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'archived')),
    effective_from          DATE NOT NULL,
    effective_to            DATE,
    base_currency           TEXT NOT NULL DEFAULT 'USD',
    scope_entity            TEXT NOT NULL DEFAULT 'all' CHECK (scope_entity IN ('all', 'personal', 'trust')),
    scope_wrapper           TEXT NOT NULL DEFAULT 'all' CHECK (scope_wrapper IN ('all', 'taxable', 'tax_deferred', 'tax_exempt')),
    scope_owner             TEXT NOT NULL DEFAULT 'all' CHECK (scope_owner IN ('all', 'Principal', 'Spouse', 'joint')),
    scope_account_types     TEXT[],
    drift_threshold         NUMERIC(8,6) NOT NULL DEFAULT 0.03 CHECK (drift_threshold >= 0),
    rebalance_band_abs      NUMERIC(8,6),
    review_cadence          TEXT,
    notes                   TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ips_target_profiles_effective_dates_chk
        CHECK (effective_to IS NULL OR effective_to >= effective_from),
    CONSTRAINT ips_target_profiles_code_effective_unique UNIQUE (profile_code, effective_from)
);

CREATE TABLE IF NOT EXISTS ips_target_allocations (
    id                      SERIAL PRIMARY KEY,
    profile_id              INTEGER NOT NULL REFERENCES ips_target_profiles(id) ON DELETE CASCADE,
    bucket_key              TEXT NOT NULL,
    target_weight           NUMERIC(10,8) NOT NULL CHECK (target_weight >= 0),
    min_weight              NUMERIC(10,8),
    max_weight              NUMERIC(10,8),
    tilt_tag                TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ips_target_allocations_unique UNIQUE (profile_id, bucket_key),
    CONSTRAINT ips_target_allocations_bounds_chk
        CHECK (
            (min_weight IS NULL OR min_weight >= 0)
            AND (max_weight IS NULL OR max_weight >= 0)
            AND (min_weight IS NULL OR min_weight <= target_weight)
            AND (max_weight IS NULL OR max_weight >= target_weight)
        )
);

CREATE TABLE IF NOT EXISTS ips_bucket_overrides (
    id                      SERIAL PRIMARY KEY,
    symbol                  TEXT NOT NULL,
    data_source             TEXT NOT NULL DEFAULT 'YAHOO',
    override_bucket_key     TEXT NOT NULL,
    scope_entity            TEXT NOT NULL DEFAULT 'all' CHECK (scope_entity IN ('all', 'personal', 'trust')),
    scope_wrapper           TEXT NOT NULL DEFAULT 'all' CHECK (scope_wrapper IN ('all', 'taxable', 'tax_deferred', 'tax_exempt')),
    scope_owner             TEXT NOT NULL DEFAULT 'all' CHECK (scope_owner IN ('all', 'Principal', 'Spouse', 'joint')),
    scope_account_types     TEXT[],
    active                  BOOLEAN NOT NULL DEFAULT TRUE,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ips_profiles_scope
ON ips_target_profiles(status, effective_from DESC, effective_to, scope_entity, scope_wrapper, scope_owner);
CREATE INDEX IF NOT EXISTS idx_ips_profiles_account_types_gin
ON ips_target_profiles USING GIN (scope_account_types);
CREATE INDEX IF NOT EXISTS idx_ips_allocations_profile ON ips_target_allocations(profile_id);
CREATE INDEX IF NOT EXISTS idx_ips_overrides_symbol_scope
ON ips_bucket_overrides(symbol, data_source, active, scope_entity, scope_wrapper, scope_owner);
CREATE INDEX IF NOT EXISTS idx_ips_overrides_account_types_gin
ON ips_bucket_overrides USING GIN (scope_account_types);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ips_overrides_unique_active
ON ips_bucket_overrides (
    symbol,
    data_source,
    scope_entity,
    scope_wrapper,
    scope_owner,
    COALESCE(scope_account_types, '{}'::text[])
)
WHERE active = TRUE;

COMMIT;
