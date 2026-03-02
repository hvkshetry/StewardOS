-- Estate Planning Graph — v1 Schema
-- Apply: psql -h localhost -p 5433 -U estate -d estate_planning -f schema.sql

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


-- ─── Estate-Planning Scope Note ─────────────────────────────────
-- Valuation history, PL/CFS/BS facts, XBRL, and OCF storage were
-- intentionally removed from the estate-planning schema. Those
-- datasets now live in finance-graph as the single source of truth.

CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_class ON asset_taxonomy(asset_class_id);
CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_subclass ON asset_taxonomy(asset_subclass_id);
CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_country_region ON asset_taxonomy(country_code, region_code);
CREATE INDEX IF NOT EXISTS idx_assets_jurisdiction ON assets(jurisdiction_id);
CREATE INDEX IF NOT EXISTS idx_real_estate_country_state ON real_estate_assets(country_code, state_code);

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
