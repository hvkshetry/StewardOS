BEGIN;

CREATE SCHEMA IF NOT EXISTS estate;
SET search_path TO estate;

CREATE TABLE IF NOT EXISTS asset_classes (
    id              SERIAL PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asset_subclasses (
    id              SERIAL PRIMARY KEY,
    asset_class_id  INTEGER NOT NULL REFERENCES asset_classes(id),
    code            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS asset_taxonomy (
    asset_id            INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    asset_class_id      INTEGER NOT NULL REFERENCES asset_classes(id),
    asset_subclass_id   INTEGER REFERENCES asset_subclasses(id),
    country_code        TEXT,
    region_code         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS real_estate_assets (
    asset_id             INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    country_code         TEXT NOT NULL,
    state_code           TEXT,
    city                 TEXT,
    postal_code          TEXT,
    address_line1        TEXT,
    property_type        TEXT,
    land_area            NUMERIC(18,4),
    land_area_unit       TEXT,
    building_area        NUMERIC(18,4),
    building_area_unit   TEXT,
    bedrooms             INTEGER,
    bathrooms            NUMERIC(4,2),
    year_built           INTEGER,
    parcel_id            TEXT,
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS valuation_observations (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    method_code         TEXT NOT NULL,
    source              TEXT NOT NULL,
    value_amount        NUMERIC(18,2) NOT NULL,
    value_currency      TEXT NOT NULL DEFAULT 'USD',
    valuation_date      DATE NOT NULL,
    confidence_score    NUMERIC(5,4),
    notes               TEXT,
    evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS valuation_comps (
    id                         SERIAL PRIMARY KEY,
    valuation_observation_id   INTEGER NOT NULL REFERENCES valuation_observations(id) ON DELETE CASCADE,
    comp_identifier            TEXT,
    address                    TEXT,
    city                       TEXT,
    state_code                 TEXT,
    country_code               TEXT,
    valuation_amount           NUMERIC(18,2),
    valuation_currency         TEXT NOT NULL DEFAULT 'USD',
    valuation_date             DATE,
    distance_km                NUMERIC(10,3),
    adjustment_notes           TEXT,
    raw_data                   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reporting_periods (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    fiscal_year         INTEGER,
    fiscal_period       TEXT,
    statement_currency  TEXT NOT NULL DEFAULT 'USD',
    source              TEXT NOT NULL DEFAULT 'manual',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS income_statement_facts (
    id                  SERIAL PRIMARY KEY,
    reporting_period_id INTEGER NOT NULL REFERENCES reporting_periods(id) ON DELETE CASCADE,
    line_item_code      TEXT NOT NULL,
    line_item_label     TEXT,
    value_amount        NUMERIC(20,4),
    value_currency      TEXT NOT NULL DEFAULT 'USD',
    source              TEXT NOT NULL DEFAULT 'manual',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT income_statement_fact_unique UNIQUE (reporting_period_id, line_item_code, source)
);

CREATE TABLE IF NOT EXISTS cash_flow_statement_facts (
    id                  SERIAL PRIMARY KEY,
    reporting_period_id INTEGER NOT NULL REFERENCES reporting_periods(id) ON DELETE CASCADE,
    line_item_code      TEXT NOT NULL,
    line_item_label     TEXT,
    value_amount        NUMERIC(20,4),
    value_currency      TEXT NOT NULL DEFAULT 'USD',
    source              TEXT NOT NULL DEFAULT 'manual',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT cash_flow_statement_fact_unique UNIQUE (reporting_period_id, line_item_code, source)
);

CREATE TABLE IF NOT EXISTS balance_sheet_facts (
    id                  SERIAL PRIMARY KEY,
    reporting_period_id INTEGER NOT NULL REFERENCES reporting_periods(id) ON DELETE CASCADE,
    line_item_code      TEXT NOT NULL,
    line_item_label     TEXT,
    value_amount        NUMERIC(20,4),
    value_currency      TEXT NOT NULL DEFAULT 'USD',
    source              TEXT NOT NULL DEFAULT 'manual',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT balance_sheet_fact_unique UNIQUE (reporting_period_id, line_item_code, source)
);

CREATE TABLE IF NOT EXISTS xbrl_reports (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER REFERENCES assets(id) ON DELETE SET NULL,
    accession_number    TEXT NOT NULL,
    cik                 TEXT,
    ticker              TEXT,
    filing_date         DATE,
    source              TEXT NOT NULL DEFAULT 'sec-edgar',
    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xbrl_report_unique UNIQUE (accession_number)
);

CREATE TABLE IF NOT EXISTS xbrl_concepts (
    id                  SERIAL PRIMARY KEY,
    concept_qname       TEXT NOT NULL UNIQUE,
    namespace           TEXT,
    local_name          TEXT,
    label               TEXT,
    data_type           TEXT,
    balance             TEXT,
    period_type         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS xbrl_contexts (
    id                  SERIAL PRIMARY KEY,
    xbrl_report_id      INTEGER NOT NULL REFERENCES xbrl_reports(id) ON DELETE CASCADE,
    context_ref         TEXT NOT NULL,
    entity_identifier   TEXT,
    period_start        DATE,
    period_end          DATE,
    instant_date        DATE,
    dimensions          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xbrl_context_unique UNIQUE (xbrl_report_id, context_ref)
);

CREATE TABLE IF NOT EXISTS xbrl_units (
    id                  SERIAL PRIMARY KEY,
    xbrl_report_id      INTEGER NOT NULL REFERENCES xbrl_reports(id) ON DELETE CASCADE,
    unit_ref            TEXT NOT NULL,
    measure             TEXT,
    numerator           TEXT,
    denominator         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT xbrl_unit_unique UNIQUE (xbrl_report_id, unit_ref)
);

CREATE TABLE IF NOT EXISTS xbrl_facts (
    id                  SERIAL PRIMARY KEY,
    xbrl_report_id      INTEGER NOT NULL REFERENCES xbrl_reports(id) ON DELETE CASCADE,
    concept_id          INTEGER NOT NULL REFERENCES xbrl_concepts(id),
    context_id          INTEGER REFERENCES xbrl_contexts(id),
    unit_id             INTEGER REFERENCES xbrl_units(id),
    fact_value_text     TEXT,
    fact_value_numeric  NUMERIC(30,10),
    decimals            TEXT,
    precision           TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ocf_documents (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER REFERENCES assets(id) ON DELETE SET NULL,
    ocf_version         TEXT,
    document_hash       TEXT NOT NULL UNIQUE,
    validation_status   TEXT NOT NULL DEFAULT 'unknown',
    validation_errors   JSONB NOT NULL DEFAULT '[]'::jsonb,
    payload             JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ocf_instruments (
    id                  SERIAL PRIMARY KEY,
    ocf_document_id     INTEGER NOT NULL REFERENCES ocf_documents(id) ON DELETE CASCADE,
    instrument_id       TEXT NOT NULL,
    instrument_type     TEXT,
    security_name       TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ocf_instrument_unique UNIQUE (ocf_document_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS ocf_positions (
    id                  SERIAL PRIMARY KEY,
    ocf_document_id     INTEGER NOT NULL REFERENCES ocf_documents(id) ON DELETE CASCADE,
    instrument_id       TEXT,
    stakeholder_name    TEXT,
    quantity            NUMERIC(30,10),
    ownership_pct       NUMERIC(12,6),
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_class ON asset_taxonomy(asset_class_id);
CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_subclass ON asset_taxonomy(asset_subclass_id);
CREATE INDEX IF NOT EXISTS idx_real_estate_country_state ON real_estate_assets(country_code, state_code);
CREATE INDEX IF NOT EXISTS idx_valuation_observations_asset_date ON valuation_observations(asset_id, valuation_date DESC);
CREATE INDEX IF NOT EXISTS idx_reporting_periods_asset_end ON reporting_periods(asset_id, period_end DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reporting_periods_unique
ON reporting_periods(asset_id, period_start, period_end, COALESCE(fiscal_period, ''));
CREATE INDEX IF NOT EXISTS idx_income_statement_period ON income_statement_facts(reporting_period_id);
CREATE INDEX IF NOT EXISTS idx_cash_flow_statement_period ON cash_flow_statement_facts(reporting_period_id);
CREATE INDEX IF NOT EXISTS idx_balance_sheet_period ON balance_sheet_facts(reporting_period_id);
CREATE INDEX IF NOT EXISTS idx_xbrl_fact_report ON xbrl_facts(xbrl_report_id);
CREATE INDEX IF NOT EXISTS idx_xbrl_fact_concept ON xbrl_facts(concept_id);
CREATE INDEX IF NOT EXISTS idx_ocf_positions_doc ON ocf_positions(ocf_document_id);

INSERT INTO asset_classes (code, name, description) VALUES
    ('real_estate', 'Real Estate', 'Real property including residential, land, commercial, and agricultural holdings'),
    ('private_equity', 'Private Equity', 'Direct private company ownership and private fund interests')
ON CONFLICT (code) DO NOTHING;

INSERT INTO asset_subclasses (asset_class_id, code, name, description)
SELECT ac.id, 'real_estate_residential', 'Residential Real Estate', 'Primary and investment residential properties'
FROM asset_classes ac
WHERE ac.code = 'real_estate'
ON CONFLICT (code) DO NOTHING;

INSERT INTO asset_subclasses (asset_class_id, code, name, description)
SELECT ac.id, 'real_estate_land', 'Land', 'Raw land and non-income-producing land parcels'
FROM asset_classes ac
WHERE ac.code = 'real_estate'
ON CONFLICT (code) DO NOTHING;

INSERT INTO asset_subclasses (asset_class_id, code, name, description)
SELECT ac.id, 'private_equity_direct', 'Direct Private Equity', 'Direct equity stakes in private businesses'
FROM asset_classes ac
WHERE ac.code = 'private_equity'
ON CONFLICT (code) DO NOTHING;

COMMIT;
