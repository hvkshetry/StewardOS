BEGIN;
SET search_path TO estate;

-- ─── Person/Entity Extensions ────────────────────────────────────
ALTER TABLE people ADD COLUMN IF NOT EXISTS death_date DATE;
ALTER TABLE people ADD COLUMN IF NOT EXISTS place_of_birth TEXT;
ALTER TABLE people ADD COLUMN IF NOT EXISTS tax_residencies TEXT[];
ALTER TABLE people ADD COLUMN IF NOT EXISTS incapacity_status TEXT;

ALTER TABLE entities ADD COLUMN IF NOT EXISTS governing_law_jurisdiction_id INTEGER REFERENCES jurisdictions(id);
ALTER TABLE entities ADD COLUMN IF NOT EXISTS governing_law_notes TEXT;

-- ─── Family Relationship Graph ───────────────────────────────────
CREATE TABLE IF NOT EXISTS person_relationships (
    id                    SERIAL PRIMARY KEY,
    person_id             INTEGER NOT NULL REFERENCES people(id),
    related_person_id     INTEGER NOT NULL REFERENCES people(id),
    relationship_type     TEXT NOT NULL, -- spouse, child, parent, dependent, sibling, guardian
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

-- ─── Fiduciary / Governance Roles ───────────────────────────────
CREATE TABLE IF NOT EXISTS entity_roles (
    id                       SERIAL PRIMARY KEY,
    entity_id                INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    holder_person_id         INTEGER REFERENCES people(id),
    holder_entity_id         INTEGER REFERENCES entities(id),
    role_type                TEXT NOT NULL, -- trustee, executor, protector, manager, director, agent, karta, guardian
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

-- ─── Typed Identifier Tables ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS person_identifiers (
    id                       SERIAL PRIMARY KEY,
    person_id                INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    identifier_type          TEXT NOT NULL, -- SSN, PAN, Passport, Aadhaar, etc.
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
    identifier_type          TEXT NOT NULL, -- EIN, LEI, CIK, CIN, LLPIN, GSTIN, state_file_number
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
    identifier_type          TEXT NOT NULL, -- parcel_id, vin, demat_account, folio, etc.
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

-- ─── Beneficial Interests (ownership semantics) ──────────────────
CREATE TABLE IF NOT EXISTS beneficial_interests (
    id                    SERIAL PRIMARY KEY,
    ownership_path_id     INTEGER REFERENCES ownership_paths(id) ON DELETE SET NULL,
    owner_person_id       INTEGER REFERENCES people(id),
    owner_entity_id       INTEGER REFERENCES entities(id),
    subject_entity_id     INTEGER REFERENCES entities(id),
    subject_asset_id      INTEGER REFERENCES assets(id),
    interest_type         TEXT NOT NULL, -- shareholding, voting_rights, board_appointment, settlor, trustee, beneficiary
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

-- ─── Succession Planning ─────────────────────────────────────────
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
    beneficiary_class           TEXT NOT NULL DEFAULT 'primary', -- primary, contingent, alternate
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
    trigger_type                TEXT NOT NULL, -- death, incapacity, age_attained, discretionary, calendar_date, other
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

-- ─── Compliance Workflow ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS compliance_obligations (
    id                          SERIAL PRIMARY KEY,
    title                       TEXT NOT NULL,
    obligation_type             TEXT NOT NULL, -- annual_report, franchise_tax, k1_distribution, trust_return, registration_renewal
    jurisdiction_id             INTEGER REFERENCES jurisdictions(id),
    entity_type_id              INTEGER REFERENCES entity_types(id),
    recurrence                  TEXT NOT NULL DEFAULT 'annual',
    due_rule                    TEXT, -- e.g. MM-DD, fiscal_year_end+90d
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
    status                      TEXT NOT NULL DEFAULT 'pending', -- pending, in_progress, submitted, accepted, rejected, waived
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
    evidence_type               TEXT NOT NULL, -- receipt, filing_confirmation, rejection_notice, correspondence
    evidence_ref                TEXT,
    status                      TEXT NOT NULL DEFAULT 'submitted',
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_compliance_evidence_instance ON compliance_evidence(compliance_instance_id);

-- ─── Paperless-Scoped Document Overlay ───────────────────────────
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
    role                        TEXT NOT NULL, -- signatory, witness, notary, executor, trustee, attorney
    signed_at                   TIMESTAMPTZ,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_participants_doc ON document_participants(paperless_doc_id);
CREATE INDEX IF NOT EXISTS idx_document_participants_person ON document_participants(person_id);

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

CREATE INDEX IF NOT EXISTS idx_document_review_policies_next_date ON document_review_policies(next_review_date);

-- Keep local documents table as compatibility header but make Paperless ID unique.
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

-- ─── Estate Provenance / Audit Assertions ───────────────────────
CREATE TABLE IF NOT EXISTS record_assertions (
    id                          SERIAL PRIMARY KEY,
    record_type                 TEXT NOT NULL, -- person, entity, asset, ownership_path, document, compliance_instance, etc.
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
