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
    CONSTRAINT asset_has_owner CHECK (num_nonnulls(owner_entity_id, owner_person_id) = 1)
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

-- ─── Comprehensive Estate Ops Extensions ─────────────────────────
ALTER TABLE people ADD COLUMN IF NOT EXISTS death_date DATE;
ALTER TABLE people ADD COLUMN IF NOT EXISTS place_of_birth TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS tax_residencies TEXT[];
ALTER TABLE people ADD COLUMN IF NOT EXISTS incapacity_status TEXT;

ALTER TABLE entities ADD COLUMN IF NOT EXISTS governing_law_jurisdiction_id INTEGER REFERENCES jurisdictions(id);
ALTER TABLE entities ADD COLUMN IF NOT EXISTS governing_law_notes TEXT;

CREATE TABLE IF NOT EXISTS person_relationships (
    id                    SERIAL PRIMARY KEY,
    person_id             INTEGER NOT NULL REFERENCES people(id),
    related_person_id     INTEGER NOT NULL REFERENCES people(id),
    relationship_type     TEXT NOT NULL,
    start_date            DATE,
    end_date              DATE,
    jurisdiction_code     TEXT REFERENCES jurisdictions(code),
    source_paperless_doc_id INTEGER,
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT person_relationships_no_self CHECK (person_id <> related_person_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_person_relationships_window
ON person_relationships (person_id, related_person_id, relationship_type, COALESCE(start_date, DATE '1900-01-01'));
CREATE INDEX IF NOT EXISTS idx_person_relationships_related ON person_relationships(related_person_id);

CREATE TABLE IF NOT EXISTS entity_roles (
    id                       SERIAL PRIMARY KEY,
    entity_id                INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    holder_person_id         INTEGER REFERENCES people(id),
    holder_entity_id         INTEGER REFERENCES entities(id),
    role_type                TEXT NOT NULL,
    authority_scope          JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_date           DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date                 DATE,
    appointment_paperless_doc_id INTEGER,
    removal_paperless_doc_id INTEGER,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT entity_roles_holder_one CHECK (
        (holder_person_id IS NOT NULL)::int + (holder_entity_id IS NOT NULL)::int = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_entity_roles_entity ON entity_roles(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_roles_holder_person ON entity_roles(holder_person_id);
CREATE INDEX IF NOT EXISTS idx_entity_roles_holder_entity ON entity_roles(holder_entity_id);

CREATE TABLE IF NOT EXISTS person_identifiers (
    id                       SERIAL PRIMARY KEY,
    person_id                INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    identifier_type          TEXT NOT NULL,
    identifier_value         TEXT NOT NULL,
    jurisdiction_code        TEXT REFERENCES jurisdictions(code),
    issuing_authority        TEXT,
    issue_date               DATE,
    expiry_date              DATE,
    status                   TEXT NOT NULL DEFAULT 'active',
    verification_paperless_doc_id INTEGER,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT person_identifiers_unique UNIQUE (person_id, identifier_type, identifier_value)
);

CREATE TABLE IF NOT EXISTS entity_identifiers (
    id                       SERIAL PRIMARY KEY,
    entity_id                INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    identifier_type          TEXT NOT NULL,
    identifier_value         TEXT NOT NULL,
    jurisdiction_code        TEXT REFERENCES jurisdictions(code),
    issuing_authority        TEXT,
    issue_date               DATE,
    expiry_date              DATE,
    status                   TEXT NOT NULL DEFAULT 'active',
    verification_paperless_doc_id INTEGER,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT entity_identifiers_unique UNIQUE (entity_id, identifier_type, identifier_value)
);

CREATE TABLE IF NOT EXISTS asset_identifiers (
    id                       SERIAL PRIMARY KEY,
    asset_id                 INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    identifier_type          TEXT NOT NULL,
    identifier_value         TEXT NOT NULL,
    jurisdiction_code        TEXT REFERENCES jurisdictions(code),
    issuing_authority        TEXT,
    issue_date               DATE,
    expiry_date              DATE,
    status                   TEXT NOT NULL DEFAULT 'active',
    verification_paperless_doc_id INTEGER,
    notes                    TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT asset_identifiers_unique UNIQUE (asset_id, identifier_type, identifier_value)
);

CREATE TABLE IF NOT EXISTS beneficial_interests (
    id                    SERIAL PRIMARY KEY,
    ownership_path_id     INTEGER REFERENCES ownership_paths(id) ON DELETE SET NULL,
    owner_person_id       INTEGER REFERENCES people(id),
    owner_entity_id       INTEGER REFERENCES entities(id),
    subject_entity_id     INTEGER REFERENCES entities(id),
    subject_asset_id      INTEGER REFERENCES assets(id),
    interest_type         TEXT NOT NULL,
    direct_or_indirect    TEXT NOT NULL DEFAULT 'unknown',
    beneficial_flag       BOOLEAN NOT NULL DEFAULT FALSE,
    share_exact           NUMERIC(7,4),
    share_min             NUMERIC(7,4),
    share_max             NUMERIC(7,4),
    assertion_source      TEXT,
    start_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    end_date              DATE,
    notes                 TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beneficial_interests_owner_one CHECK (
        (owner_person_id IS NOT NULL)::int + (owner_entity_id IS NOT NULL)::int = 1
    ),
    CONSTRAINT beneficial_interests_subject_one CHECK (
        (subject_entity_id IS NOT NULL)::int + (subject_asset_id IS NOT NULL)::int = 1
    ),
    CONSTRAINT beneficial_interests_directness CHECK (
        direct_or_indirect IN ('direct', 'indirect', 'unknown')
    ),
    CONSTRAINT beneficial_interests_share_range CHECK (
        (share_exact IS NULL OR (share_exact >= 0 AND share_exact <= 100))
        AND (share_min IS NULL OR (share_min >= 0 AND share_min <= 100))
        AND (share_max IS NULL OR (share_max >= 0 AND share_max <= 100))
        AND (share_min IS NULL OR share_max IS NULL OR share_min <= share_max)
    )
);

CREATE INDEX IF NOT EXISTS idx_beneficial_interests_owner_person ON beneficial_interests(owner_person_id);
CREATE INDEX IF NOT EXISTS idx_beneficial_interests_owner_entity ON beneficial_interests(owner_entity_id);
CREATE INDEX IF NOT EXISTS idx_beneficial_interests_subject_entity ON beneficial_interests(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_beneficial_interests_subject_asset ON beneficial_interests(subject_asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_beneficial_interests_ownership_path
ON beneficial_interests(ownership_path_id) WHERE ownership_path_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS succession_plans (
    id                          SERIAL PRIMARY KEY,
    name                        TEXT NOT NULL,
    governing_law_jurisdiction_id INTEGER REFERENCES jurisdictions(id),
    grantor_person_id           INTEGER REFERENCES people(id),
    sponsor_entity_id           INTEGER REFERENCES entities(id),
    primary_instrument_paperless_doc_id INTEGER,
    status                      TEXT NOT NULL DEFAULT 'active',
    effective_date              DATE,
    termination_date            DATE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS beneficiary_designations (
    id                          SERIAL PRIMARY KEY,
    succession_plan_id          INTEGER NOT NULL REFERENCES succession_plans(id) ON DELETE CASCADE,
    beneficiary_person_id       INTEGER REFERENCES people(id),
    beneficiary_entity_id       INTEGER REFERENCES entities(id),
    beneficiary_class           TEXT NOT NULL DEFAULT 'primary',
    share_percentage            NUMERIC(7,4),
    per_stirpes                 BOOLEAN NOT NULL DEFAULT FALSE,
    per_capita                  BOOLEAN NOT NULL DEFAULT FALSE,
    anti_lapse                  BOOLEAN NOT NULL DEFAULT FALSE,
    condition_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_date                  DATE,
    end_date                    DATE,
    source_paperless_doc_id     INTEGER,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT beneficiary_designation_target_one CHECK (
        (beneficiary_person_id IS NOT NULL)::int + (beneficiary_entity_id IS NOT NULL)::int = 1
    ),
    CONSTRAINT beneficiary_designation_share_range CHECK (
        share_percentage IS NULL OR (share_percentage >= 0 AND share_percentage <= 100)
    )
);

CREATE INDEX IF NOT EXISTS idx_beneficiary_designations_plan ON beneficiary_designations(succession_plan_id);

CREATE TABLE IF NOT EXISTS distribution_rules (
    id                          SERIAL PRIMARY KEY,
    succession_plan_id          INTEGER NOT NULL REFERENCES succession_plans(id) ON DELETE CASCADE,
    rule_name                   TEXT NOT NULL,
    trigger_type                TEXT NOT NULL,
    trigger_details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    minimum_age                 INTEGER,
    trustee_discretion_standard TEXT,
    termination_condition       TEXT,
    source_paperless_doc_id     INTEGER,
    priority                    INTEGER NOT NULL DEFAULT 100,
    active                      BOOLEAN NOT NULL DEFAULT TRUE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_distribution_rules_plan ON distribution_rules(succession_plan_id);

CREATE TABLE IF NOT EXISTS compliance_obligations (
    id                          SERIAL PRIMARY KEY,
    title                       TEXT NOT NULL,
    obligation_type             TEXT NOT NULL,
    jurisdiction_id             INTEGER REFERENCES jurisdictions(id),
    entity_type_id              INTEGER REFERENCES entity_types(id),
    recurrence                  TEXT NOT NULL DEFAULT 'annual',
    due_rule                    TEXT,
    grace_days                  INTEGER NOT NULL DEFAULT 0,
    penalty_notes               TEXT,
    default_owner_person_id     INTEGER REFERENCES people(id),
    active                      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS compliance_instances (
    id                          SERIAL PRIMARY KEY,
    obligation_id               INTEGER NOT NULL REFERENCES compliance_obligations(id) ON DELETE CASCADE,
    entity_id                   INTEGER REFERENCES entities(id),
    person_id                   INTEGER REFERENCES people(id),
    period_start                DATE,
    period_end                  DATE,
    due_date                    DATE NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'pending',
    assigned_to_person_id       INTEGER REFERENCES people(id),
    submitted_at                TIMESTAMPTZ,
    accepted_at                 TIMESTAMPTZ,
    rejected_at                 TIMESTAMPTZ,
    rejection_reason            TEXT,
    completion_notes            TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_instances_due ON compliance_instances(due_date, status);

CREATE TABLE IF NOT EXISTS compliance_evidence (
    id                          SERIAL PRIMARY KEY,
    compliance_instance_id      INTEGER NOT NULL REFERENCES compliance_instances(id) ON DELETE CASCADE,
    paperless_doc_id            INTEGER,
    evidence_type               TEXT NOT NULL,
    evidence_ref                TEXT,
    status                      TEXT NOT NULL DEFAULT 'submitted',
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_metadata (
    paperless_doc_id            INTEGER PRIMARY KEY,
    entity_id                   INTEGER REFERENCES entities(id),
    asset_id                    INTEGER REFERENCES assets(id),
    person_id                   INTEGER REFERENCES people(id),
    jurisdiction_id             INTEGER REFERENCES jurisdictions(id),
    doc_purpose_type            TEXT NOT NULL DEFAULT 'other',
    effective_date              DATE,
    expiry_date                 DATE,
    last_reviewed               DATE,
    status                      TEXT NOT NULL DEFAULT 'active',
    source_snapshot_title       TEXT,
    source_snapshot_doc_type    TEXT,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_version_links (
    id                          SERIAL PRIMARY KEY,
    paperless_doc_id            INTEGER NOT NULL REFERENCES document_metadata(paperless_doc_id) ON DELETE CASCADE,
    supersedes_paperless_doc_id INTEGER NOT NULL REFERENCES document_metadata(paperless_doc_id) ON DELETE CASCADE,
    version_reason              TEXT,
    asserted_by                 TEXT,
    asserted_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes                       TEXT,
    CONSTRAINT document_version_links_no_self CHECK (paperless_doc_id <> supersedes_paperless_doc_id),
    CONSTRAINT document_version_links_unique UNIQUE (paperless_doc_id, supersedes_paperless_doc_id)
);

CREATE TABLE IF NOT EXISTS document_assertions (
    id                          SERIAL PRIMARY KEY,
    paperless_doc_id            INTEGER NOT NULL REFERENCES document_metadata(paperless_doc_id) ON DELETE CASCADE,
    assertion_type              TEXT NOT NULL,
    asserted_value_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_system               TEXT NOT NULL DEFAULT 'estate-planning',
    source_record_id            TEXT,
    confidence                  NUMERIC(5,4),
    asserted_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes                       TEXT
);

CREATE TABLE IF NOT EXISTS document_participants (
    id                          SERIAL PRIMARY KEY,
    paperless_doc_id            INTEGER NOT NULL REFERENCES document_metadata(paperless_doc_id) ON DELETE CASCADE,
    person_id                   INTEGER NOT NULL REFERENCES people(id),
    role                        TEXT NOT NULL,
    signed_at                   TIMESTAMPTZ,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_review_policies (
    paperless_doc_id            INTEGER PRIMARY KEY REFERENCES document_metadata(paperless_doc_id) ON DELETE CASCADE,
    review_cadence              TEXT NOT NULL DEFAULT 'annual',
    next_review_date            DATE,
    renewal_window_days         INTEGER NOT NULL DEFAULT 30,
    owner_person_id             INTEGER REFERENCES people(id),
    policy_status               TEXT NOT NULL DEFAULT 'active',
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE paperless_doc_id IS NOT NULL
        GROUP BY paperless_doc_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE NOTICE 'Skipping documents_paperless_doc_id_key due to duplicate paperless_doc_id values';
    ELSIF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'documents_paperless_doc_id_key'
          AND conrelid = 'estate.documents'::regclass
    ) THEN
        ALTER TABLE documents
        ADD CONSTRAINT documents_paperless_doc_id_key UNIQUE (paperless_doc_id);
    END IF;
END $$;

-- Backfill document overlay from existing document links.
WITH dedup_docs AS (
    SELECT DISTINCT ON (d.paperless_doc_id)
        d.paperless_doc_id,
        d.entity_id,
        d.asset_id,
        d.person_id,
        d.jurisdiction_id,
        d.doc_type,
        d.effective_date,
        d.expiry_date,
        d.last_reviewed,
        d.title,
        d.notes
    FROM documents d
    WHERE d.paperless_doc_id IS NOT NULL
    ORDER BY d.paperless_doc_id, d.updated_at DESC NULLS LAST, d.id DESC
)
INSERT INTO document_metadata (
    paperless_doc_id, entity_id, asset_id, person_id, jurisdiction_id,
    doc_purpose_type, effective_date, expiry_date, last_reviewed, source_snapshot_title,
    source_snapshot_doc_type, notes
)
SELECT
    d.paperless_doc_id, d.entity_id, d.asset_id, d.person_id, d.jurisdiction_id,
    COALESCE(NULLIF(d.doc_type, ''), 'other'),
    d.effective_date, d.expiry_date, d.last_reviewed, d.title, d.doc_type, d.notes
FROM dedup_docs d
ON CONFLICT (paperless_doc_id) DO UPDATE SET
    entity_id = EXCLUDED.entity_id,
    asset_id = EXCLUDED.asset_id,
    person_id = EXCLUDED.person_id,
    jurisdiction_id = EXCLUDED.jurisdiction_id,
    doc_purpose_type = EXCLUDED.doc_purpose_type,
    effective_date = EXCLUDED.effective_date,
    expiry_date = EXCLUDED.expiry_date,
    last_reviewed = EXCLUDED.last_reviewed,
    source_snapshot_title = COALESCE(EXCLUDED.source_snapshot_title, document_metadata.source_snapshot_title),
    source_snapshot_doc_type = COALESCE(EXCLUDED.source_snapshot_doc_type, document_metadata.source_snapshot_doc_type),
    notes = COALESCE(EXCLUDED.notes, document_metadata.notes),
    updated_at = now();

CREATE TABLE IF NOT EXISTS record_assertions (
    id                          SERIAL PRIMARY KEY,
    record_type                 TEXT NOT NULL,
    record_id                   TEXT NOT NULL,
    source_system               TEXT NOT NULL,
    source_record_id            TEXT,
    asserted_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    confidence                  NUMERIC(5,4),
    raw_payload_hash            TEXT,
    changed_by                  TEXT,
    assertion_payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_record_assertions_record ON record_assertions(record_type, record_id);
CREATE INDEX IF NOT EXISTS idx_record_assertions_source ON record_assertions(source_system, source_record_id);


-- Ensure estate application role can access new estate schema objects.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'estate') THEN
        GRANT USAGE ON SCHEMA estate TO estate;
        GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON ALL TABLES IN SCHEMA estate TO estate;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA estate TO estate;

        ALTER DEFAULT PRIVILEGES IN SCHEMA estate
            GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON TABLES TO estate;
        ALTER DEFAULT PRIVILEGES IN SCHEMA estate
            GRANT USAGE, SELECT ON SEQUENCES TO estate;
    END IF;
END $$;

COMMIT;
