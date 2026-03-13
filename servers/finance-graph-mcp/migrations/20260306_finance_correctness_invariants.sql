BEGIN;

CREATE SCHEMA IF NOT EXISTS finance;
SET search_path TO finance, public;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM assets
        WHERE num_nonnulls(owner_entity_id, owner_person_id) <> 1
    ) THEN
        RAISE EXCEPTION 'finance.assets must have exactly one owner before applying 20260306_finance_correctness_invariants.sql';
    END IF;
END
$$;

ALTER TABLE assets
    DROP CONSTRAINT IF EXISTS asset_has_owner;

ALTER TABLE assets
    ADD CONSTRAINT asset_has_owner
    CHECK (num_nonnulls(owner_entity_id, owner_person_id) = 1);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM documents
        WHERE paperless_doc_id IS NOT NULL
        GROUP BY paperless_doc_id
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'finance.documents contains duplicate non-null paperless_doc_id values; reconcile them before applying 20260306_finance_correctness_invariants.sql';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_paperless_doc_id_unique
    ON documents (paperless_doc_id);

CREATE TABLE IF NOT EXISTS document_metadata (
    paperless_doc_id            INTEGER PRIMARY KEY REFERENCES documents(paperless_doc_id) ON DELETE CASCADE,
    entity_id                   INTEGER REFERENCES entities(id),
    asset_id                    INTEGER REFERENCES assets(id),
    person_id                   INTEGER REFERENCES people(id),
    jurisdiction_id             INTEGER REFERENCES jurisdictions(id),
    doc_purpose_type            TEXT NOT NULL DEFAULT 'other',
    effective_date              DATE,
    expiry_date                 DATE,
    status                      TEXT NOT NULL DEFAULT 'active',
    source_snapshot_title       TEXT,
    source_snapshot_doc_type    TEXT,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO document_metadata (
    paperless_doc_id,
    entity_id,
    asset_id,
    person_id,
    jurisdiction_id,
    doc_purpose_type,
    effective_date,
    expiry_date,
    status,
    source_snapshot_title,
    source_snapshot_doc_type,
    notes
)
SELECT DISTINCT ON (d.paperless_doc_id)
    d.paperless_doc_id,
    d.entity_id,
    d.asset_id,
    d.person_id,
    d.jurisdiction_id,
    COALESCE(NULLIF(d.doc_type, ''), 'other'),
    d.effective_date,
    d.expiry_date,
    'active',
    d.title,
    d.doc_type,
    d.notes
FROM documents d
WHERE d.paperless_doc_id IS NOT NULL
ORDER BY d.paperless_doc_id, d.updated_at DESC NULLS LAST, d.id DESC
ON CONFLICT (paperless_doc_id) DO UPDATE SET
    entity_id = COALESCE(EXCLUDED.entity_id, document_metadata.entity_id),
    asset_id = COALESCE(EXCLUDED.asset_id, document_metadata.asset_id),
    person_id = COALESCE(EXCLUDED.person_id, document_metadata.person_id),
    jurisdiction_id = COALESCE(EXCLUDED.jurisdiction_id, document_metadata.jurisdiction_id),
    doc_purpose_type = COALESCE(EXCLUDED.doc_purpose_type, document_metadata.doc_purpose_type),
    effective_date = COALESCE(EXCLUDED.effective_date, document_metadata.effective_date),
    expiry_date = COALESCE(EXCLUDED.expiry_date, document_metadata.expiry_date),
    source_snapshot_title = COALESCE(EXCLUDED.source_snapshot_title, document_metadata.source_snapshot_title),
    source_snapshot_doc_type = COALESCE(EXCLUDED.source_snapshot_doc_type, document_metadata.source_snapshot_doc_type),
    notes = COALESCE(EXCLUDED.notes, document_metadata.notes),
    updated_at = now();

COMMIT;
