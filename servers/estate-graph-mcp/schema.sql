-- Estate Planning Knowledge Graph — v1 Schema
-- Apply: psql -h localhost -p 5433 -U estate -d personal -f schema.sql

BEGIN;

CREATE SCHEMA IF NOT EXISTS estate;
SET search_path TO estate;

-- ─── Jurisdictions ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jurisdictions (
    id              SERIAL PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,          -- US, US-CA, US-TX, IN, IN-KA
    name            TEXT NOT NULL,
    country         TEXT NOT NULL,                 -- US, IN
    parent_code     TEXT REFERENCES jurisdictions(code),
    tax_id_label    TEXT,                          -- SSN/EIN, PAN, TAN
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Entity Types ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entity_types (
    id              SERIAL PRIMARY KEY,
    code            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    jurisdiction    TEXT,                          -- NULL = universal, else country code
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── People ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS people (
    id              SERIAL PRIMARY KEY,
    legal_name      TEXT NOT NULL,
    preferred_name  TEXT,
    date_of_birth   DATE,
    citizenship     TEXT[],                        -- ['US', 'IN']
    residency_status TEXT,                         -- citizen, resident, nri, oci
    tax_id          TEXT,                          -- SSN or PAN (encrypted at rest)
    tax_id_type     TEXT,                          -- SSN, PAN
    vaultwarden_item_id TEXT,                      -- link to Vaultwarden for sensitive docs
    email           TEXT,
    phone           TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Entities (trusts, LLCs, corps, HUFs) ───────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    entity_type_id  INTEGER NOT NULL REFERENCES entity_types(id),
    jurisdiction_id INTEGER NOT NULL REFERENCES jurisdictions(id),
    status          TEXT NOT NULL DEFAULT 'active',  -- active, dissolved, pending
    formation_date  DATE,
    dissolution_date DATE,
    tax_id          TEXT,                          -- EIN, PAN, TAN
    tax_id_type     TEXT,                          -- EIN, PAN, TAN
    grantor_id      INTEGER REFERENCES people(id), -- for trusts
    trustee_id      INTEGER REFERENCES people(id), -- for trusts
    karta_id        INTEGER REFERENCES people(id), -- for HUF (India)
    registered_agent TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Assets ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assets (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    asset_type      TEXT NOT NULL,                 -- real_estate, vehicle, securities, ip, bank_account, crypto, other
    description     TEXT,
    jurisdiction_id INTEGER REFERENCES jurisdictions(id),
    owner_entity_id INTEGER REFERENCES entities(id),
    owner_person_id INTEGER REFERENCES people(id),
    current_valuation_amount NUMERIC(18,2),
    valuation_currency TEXT NOT NULL DEFAULT 'USD',
    valuation_date  DATE,
    acquisition_date DATE,
    acquisition_cost NUMERIC(18,2),
    paperless_doc_id INTEGER,                      -- link to Paperless-ngx document
    ghostfolio_account_id TEXT,                    -- link to Ghostfolio account
    address         TEXT,                          -- for real estate
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asset_has_owner CHECK (owner_entity_id IS NOT NULL OR owner_person_id IS NOT NULL)
);

-- ─── Ownership Paths (fractional ownership graph) ────────────────
CREATE TABLE IF NOT EXISTS ownership_paths (
    id              SERIAL PRIMARY KEY,
    -- owner side (exactly one)
    owner_person_id INTEGER REFERENCES people(id),
    owner_entity_id INTEGER REFERENCES entities(id),
    -- owned side (exactly one)
    owned_entity_id INTEGER REFERENCES entities(id),
    owned_asset_id  INTEGER REFERENCES assets(id),
    -- ownership details
    percentage      NUMERIC(7,4) NOT NULL CHECK (percentage > 0 AND percentage <= 100),
    units           NUMERIC(18,4),                 -- shares, units
    effective_date  DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date        DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT owner_is_one CHECK (
        (owner_person_id IS NOT NULL)::int + (owner_entity_id IS NOT NULL)::int = 1
    ),
    CONSTRAINT owned_is_one CHECK (
        (owned_entity_id IS NOT NULL)::int + (owned_asset_id IS NOT NULL)::int = 1
    )
);

-- ─── Documents (links to Paperless-ngx + Vaultwarden) ────────────
CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    doc_type        TEXT NOT NULL,                  -- trust_agreement, llc_agreement, deed, will, poa, k1, tax_return, registration, certificate, other
    paperless_doc_id INTEGER,                       -- Paperless-ngx document ID
    vaultwarden_item_id TEXT,                       -- Vaultwarden item ID (for sensitive docs)
    entity_id       INTEGER REFERENCES entities(id),
    asset_id        INTEGER REFERENCES assets(id),
    person_id       INTEGER REFERENCES people(id),
    jurisdiction_id INTEGER REFERENCES jurisdictions(id),
    effective_date  DATE,
    expiry_date     DATE,
    last_reviewed   DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Critical Dates ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS critical_dates (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL,
    date_type       TEXT NOT NULL,                  -- tax_filing, registration_renewal, trust_distribution, rmd, insurance_renewal, review, other
    due_date        DATE NOT NULL,
    entity_id       INTEGER REFERENCES entities(id),
    asset_id        INTEGER REFERENCES assets(id),
    person_id       INTEGER REFERENCES people(id),
    jurisdiction_id INTEGER REFERENCES jurisdictions(id),
    recurrence      TEXT,                           -- annual, quarterly, monthly, one-time
    notify_days_before INTEGER NOT NULL DEFAULT 30,
    completed       BOOLEAN NOT NULL DEFAULT FALSE,
    completed_date  DATE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Indexes ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type_id);
CREATE INDEX IF NOT EXISTS idx_entities_jurisdiction ON entities(jurisdiction_id);
CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_owner_entity ON assets(owner_entity_id);
CREATE INDEX IF NOT EXISTS idx_assets_owner_person ON assets(owner_person_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owner_person ON ownership_paths(owner_person_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owner_entity ON ownership_paths(owner_entity_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owned_entity ON ownership_paths(owned_entity_id);
CREATE INDEX IF NOT EXISTS idx_ownership_owned_asset ON ownership_paths(owned_asset_id);
CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_id);
CREATE INDEX IF NOT EXISTS idx_documents_asset ON documents(asset_id);
CREATE INDEX IF NOT EXISTS idx_documents_person ON documents(person_id);
CREATE INDEX IF NOT EXISTS idx_critical_dates_due ON critical_dates(due_date) WHERE NOT completed;

-- ─── Views ───────────────────────────────────────────────────────

-- Flattened ownership summary
CREATE OR REPLACE VIEW v_ownership_summary AS
SELECT
    op.id,
    COALESCE(pp.legal_name, oe.name) AS owner_name,
    CASE WHEN op.owner_person_id IS NOT NULL THEN 'person' ELSE 'entity' END AS owner_type,
    COALESCE(oe2.name, a.name) AS owned_name,
    CASE WHEN op.owned_entity_id IS NOT NULL THEN 'entity' ELSE 'asset' END AS owned_type,
    op.percentage,
    op.units,
    op.effective_date,
    op.end_date
FROM ownership_paths op
LEFT JOIN people pp ON op.owner_person_id = pp.id
LEFT JOIN entities oe ON op.owner_entity_id = oe.id
LEFT JOIN entities oe2 ON op.owned_entity_id = oe2.id
LEFT JOIN assets a ON op.owned_asset_id = a.id
WHERE op.end_date IS NULL OR op.end_date > CURRENT_DATE;

-- Net worth by jurisdiction
CREATE OR REPLACE VIEW v_net_worth_by_jurisdiction AS
SELECT
    j.code AS jurisdiction_code,
    j.name AS jurisdiction_name,
    j.country,
    a.valuation_currency AS currency,
    SUM(a.current_valuation_amount) AS total_value,
    COUNT(*) AS asset_count
FROM assets a
JOIN jurisdictions j ON a.jurisdiction_id = j.id
WHERE a.current_valuation_amount IS NOT NULL
GROUP BY j.code, j.name, j.country, a.valuation_currency;

-- ─── Recursive CTE function for transitive ownership ─────────────
-- Usage: SELECT * FROM estate.get_transitive_ownership(person_id := 1);
CREATE OR REPLACE FUNCTION get_transitive_ownership(target_person_id INTEGER)
RETURNS TABLE (
    entity_name TEXT,
    entity_id INTEGER,
    direct_pct NUMERIC,
    effective_pct NUMERIC,
    depth INTEGER,
    path TEXT[]
) LANGUAGE SQL STABLE AS $$
    WITH RECURSIVE ownership_chain AS (
        -- Base: direct person → entity ownership
        SELECT
            e.name AS entity_name,
            e.id AS entity_id,
            op.percentage::NUMERIC AS direct_pct,
            op.percentage::NUMERIC AS effective_pct,
            1 AS depth,
            ARRAY[p.legal_name, e.name] AS path
        FROM ownership_paths op
        JOIN entities e ON op.owned_entity_id = e.id
        JOIN people p ON op.owner_person_id = p.id
        WHERE op.owner_person_id = target_person_id
          AND op.owned_entity_id IS NOT NULL
          AND (op.end_date IS NULL OR op.end_date > CURRENT_DATE)

        UNION ALL

        -- Recursive: entity → entity ownership
        SELECT
            e2.name,
            e2.id,
            op2.percentage::NUMERIC,
            (oc.effective_pct * op2.percentage::NUMERIC / 100),
            oc.depth + 1,
            oc.path || e2.name
        FROM ownership_chain oc
        JOIN ownership_paths op2 ON op2.owner_entity_id = oc.entity_id
        JOIN entities e2 ON op2.owned_entity_id = e2.id
        WHERE op2.owned_entity_id IS NOT NULL
          AND (op2.end_date IS NULL OR op2.end_date > CURRENT_DATE)
          AND oc.depth < 10  -- prevent infinite loops
    )
    SELECT * FROM ownership_chain ORDER BY depth, entity_name;
$$;

-- ─── Seed: Entity Types ──────────────────────────────────────────
INSERT INTO entity_types (code, name, jurisdiction, description) VALUES
    ('REVOCABLE_TRUST',    'Revocable Living Trust',     'US', 'Grantor trust, avoids probate, revocable during lifetime'),
    ('IRREVOCABLE_TRUST',  'Irrevocable Trust',          'US', 'Cannot be modified after creation, asset protection + estate tax benefits'),
    ('LLC',                'Limited Liability Company',   'US', 'Pass-through entity, liability protection'),
    ('S_CORP',             'S Corporation',               'US', 'Pass-through, limited to 100 shareholders, SE tax savings'),
    ('C_CORP',             'C Corporation',               'US', 'Double taxation, unlimited shareholders, preferred for VC'),
    ('LP',                 'Limited Partnership',          'US', 'GP + LP structure, common for real estate and funds'),
    ('SOLE_PROP',          'Sole Proprietorship',         'US', 'No separate entity, Schedule C'),
    ('HUF',                'Hindu Undivided Family',      'IN', 'Tax entity for Hindu joint family, Karta manages'),
    ('PRIVATE_TRUST',      'Private Trust (India)',       'IN', 'Indian Trust Act 1882, specific or discretionary'),
    ('PRIVATE_LTD',        'Private Limited Company',     'IN', 'Indian Companies Act 2013, max 200 shareholders'),
    ('LLP_IN',             'Limited Liability Partnership','IN', 'LLP Act 2008, hybrid of partnership and company'),
    ('FOUNDATION',         'Private Foundation',          NULL, 'Charitable or family foundation, jurisdiction-agnostic'),
    ('PARTNERSHIP',        'General Partnership',         NULL, 'Unincorporated, unlimited liability')
ON CONFLICT (code) DO NOTHING;

-- ─── Seed: Jurisdictions ─────────────────────────────────────────
INSERT INTO jurisdictions (code, name, country, parent_code, tax_id_label) VALUES
    ('US',    'United States',    'US', NULL,  'SSN/EIN'),
    ('US-CA', 'California',       'US', 'US',  'SSN/EIN'),
    ('US-TX', 'Texas',            'US', 'US',  'SSN/EIN'),
    ('US-DE', 'Delaware',         'US', 'US',  'SSN/EIN'),
    ('US-WY', 'Wyoming',          'US', 'US',  'SSN/EIN'),
    ('US-NV', 'Nevada',           'US', 'US',  'SSN/EIN'),
    ('US-FL', 'Florida',          'US', 'US',  'SSN/EIN'),
    ('IN',    'India',            'IN', NULL,  'PAN'),
    ('IN-KA', 'Karnataka',        'IN', 'IN',  'PAN'),
    ('IN-MH', 'Maharashtra',      'IN', 'IN',  'PAN'),
    ('IN-TG', 'Telangana',        'IN', 'IN',  'PAN'),
    ('IN-DL', 'Delhi',            'IN', 'IN',  'PAN')
ON CONFLICT (code) DO NOTHING;

-- ─── Asset Taxonomy (normalized class/subclass) ─────────────────
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
    country_code        TEXT,   -- ISO country code of principal location (US, IN, etc.)
    region_code         TEXT,   -- optional state/province code
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Real Estate Detail ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS real_estate_assets (
    asset_id             INTEGER PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,
    country_code         TEXT NOT NULL,          -- US, IN
    state_code           TEXT,
    city                 TEXT,
    postal_code          TEXT,
    address_line1        TEXT,
    property_type        TEXT,                   -- residential, land, commercial, ag
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

-- ─── Valuation History ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS valuation_methods (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS valuation_observations (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    method_code         TEXT NOT NULL REFERENCES valuation_methods(code),
    source              TEXT NOT NULL,            -- rentcast, user_manual, analyst, etc.
    value_amount        NUMERIC(18,2) NOT NULL,
    value_currency      TEXT NOT NULL DEFAULT 'USD',
    valuation_date      DATE NOT NULL,
    confidence_score    NUMERIC(5,4),             -- 0.0000 - 1.0000
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

-- ─── Core Financial Statement Store (PL/CFS/BS) ──────────────────
CREATE TABLE IF NOT EXISTS reporting_periods (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    fiscal_year         INTEGER,
    fiscal_period       TEXT,                      -- FY, Q1, Q2, Q3, Q4, TTM
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

-- ─── XBRL Core Store (Arelle-inspired subset) ────────────────────
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
    concept_qname       TEXT NOT NULL UNIQUE,      -- us-gaap:Revenues
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

-- ─── OCF Store (v1.2.0 pinned schema compatibility) ──────────────
CREATE TABLE IF NOT EXISTS ocf_documents (
    id                  SERIAL PRIMARY KEY,
    asset_id            INTEGER REFERENCES assets(id) ON DELETE SET NULL,
    ocf_version         TEXT,
    document_hash       TEXT NOT NULL UNIQUE,
    validation_status   TEXT NOT NULL DEFAULT 'unknown',  -- valid, invalid, unknown
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
CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_country_region ON asset_taxonomy(country_code, region_code);
CREATE INDEX IF NOT EXISTS idx_assets_jurisdiction ON assets(jurisdiction_id);
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

INSERT INTO valuation_methods (code, name, description) VALUES
    ('rentcast_avm', 'RentCast AVM', 'US-only automated residential/land valuation from RentCast'),
    ('manual_comp', 'Manual Comparable Sales', 'User-entered comparable transactions and adjustments'),
    ('manual_mark', 'Manual Mark', 'Direct user mark-to-model or mark-to-market estimate'),
    ('income_approach', 'Income Approach', 'NOI/cap-rate or discounted cash flow from rental stream'),
    ('dcf', 'Discounted Cash Flow', 'Explicit forecast and discount-rate valuation approach')
ON CONFLICT (code) DO NOTHING;

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
SELECT ac.id, 'real_estate_commercial', 'Commercial Real Estate', 'Office, retail, industrial, and mixed-use property'
FROM asset_classes ac
WHERE ac.code = 'real_estate'
ON CONFLICT (code) DO NOTHING;

INSERT INTO asset_subclasses (asset_class_id, code, name, description)
SELECT ac.id, 'real_estate_agricultural', 'Agricultural Real Estate', 'Farm, ranch, and agricultural-use land'
FROM asset_classes ac
WHERE ac.code = 'real_estate'
ON CONFLICT (code) DO NOTHING;

INSERT INTO asset_subclasses (asset_class_id, code, name, description)
SELECT ac.id, 'private_equity_direct', 'Direct Private Equity', 'Direct equity stakes in private businesses'
FROM asset_classes ac
WHERE ac.code = 'private_equity'
ON CONFLICT (code) DO NOTHING;

COMMIT;
