BEGIN;

CREATE SCHEMA IF NOT EXISTS finance;
SET search_path TO finance;

CREATE TABLE IF NOT EXISTS ips_bucket_lookthrough (
    id                      SERIAL PRIMARY KEY,
    symbol                  TEXT NOT NULL,
    data_source             TEXT NOT NULL DEFAULT 'YAHOO',
    bucket_key              TEXT NOT NULL,
    fraction_weight         NUMERIC(10,8) NOT NULL CHECK (fraction_weight > 0 AND fraction_weight <= 1),
    source_as_of            DATE,
    scope_entity            TEXT NOT NULL DEFAULT 'all' CHECK (scope_entity IN ('all', 'personal', 'trust')),
    scope_wrapper           TEXT NOT NULL DEFAULT 'all' CHECK (scope_wrapper IN ('all', 'taxable', 'tax_deferred', 'tax_exempt')),
    scope_owner             TEXT NOT NULL DEFAULT 'all' CHECK (scope_owner IN ('all', 'Principal', 'Spouse', 'joint')),
    scope_account_types     TEXT[],
    active                  BOOLEAN NOT NULL DEFAULT TRUE,
    notes                   TEXT,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ips_lookthrough_symbol_scope
ON ips_bucket_lookthrough(symbol, data_source, active, scope_entity, scope_wrapper, scope_owner);

CREATE INDEX IF NOT EXISTS idx_ips_lookthrough_account_types_gin
ON ips_bucket_lookthrough USING GIN (scope_account_types);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ips_lookthrough_unique_active
ON ips_bucket_lookthrough (
    symbol,
    data_source,
    bucket_key,
    scope_entity,
    scope_wrapper,
    scope_owner,
    COALESCE(scope_account_types, '{}'::text[])
)
WHERE active = TRUE;

COMMIT;
