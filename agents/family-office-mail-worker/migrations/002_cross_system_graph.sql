-- 002_cross_system_graph.sql — Cross-system identity graph + lightweight request tier
-- Applies to: orchestration database on personal-db (Postgres 16.6)
-- Run after 001_initial.sql; SQLAlchemy create_all() creates tables but not
-- indexes or CHECK constraints — this migration adds those.
--
-- Safe to run whether create_all() has already created the tables or not:
-- CREATE TABLE IF NOT EXISTS is a no-op if the table exists, and the
-- DO $$ blocks retrofit constraints onto tables created by create_all().

SET search_path TO orchestration;

-- ─── Work Item Nodes (canonical internal work objects) ────────────────

CREATE TABLE IF NOT EXISTS work_item_nodes (
    node_id     TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    internal_id TEXT NOT NULL,
    workspace   TEXT,
    project_id  TEXT,
    title       TEXT,
    status      TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (node_type, internal_id)
);
CREATE INDEX IF NOT EXISTS ix_work_item_nodes_type_id ON work_item_nodes (node_type, internal_id);
CREATE INDEX IF NOT EXISTS ix_work_item_nodes_workspace ON work_item_nodes (workspace);

-- Retrofit unique constraint if table was created by create_all() without it
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_work_item_nodes_type_id' AND conrelid = 'work_item_nodes'::regclass
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'work_item_nodes'::regclass AND contype = 'u'
          AND conkey = (SELECT array_agg(attnum ORDER BY attnum) FROM pg_attribute
                        WHERE attrelid = 'work_item_nodes'::regclass AND attname IN ('node_type','internal_id'))
    ) THEN
        ALTER TABLE work_item_nodes ADD CONSTRAINT uq_work_item_nodes_type_id UNIQUE (node_type, internal_id);
    END IF;
END $$;

-- ─── External Objects (references to Gmail, Paperless, etc.) ─────────

CREATE TABLE IF NOT EXISTS external_objects (
    ext_id        TEXT PRIMARY KEY,
    system        TEXT NOT NULL,
    system_id     TEXT NOT NULL,
    display_label TEXT,
    metadata      JSONB,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (system, system_id)
);
CREATE INDEX IF NOT EXISTS ix_external_objects_system_id ON external_objects (system, system_id);

-- Retrofit unique constraint if table was created by create_all() without it
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_external_objects_system_id' AND conrelid = 'external_objects'::regclass
    ) AND NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'external_objects'::regclass AND contype = 'u'
          AND conkey = (SELECT array_agg(attnum ORDER BY attnum) FROM pg_attribute
                        WHERE attrelid = 'external_objects'::regclass AND attname IN ('system','system_id'))
    ) THEN
        ALTER TABLE external_objects ADD CONSTRAINT uq_external_objects_system_id UNIQUE (system, system_id);
    END IF;
END $$;

-- ─── Edges (typed relations between nodes/external objects) ──────────

CREATE TABLE IF NOT EXISTS edges (
    edge_id         TEXT PRIMARY KEY,
    relation_type   TEXT NOT NULL,
    source_node_id  TEXT REFERENCES work_item_nodes(node_id),
    source_ext_id   TEXT REFERENCES external_objects(ext_id),
    target_node_id  TEXT REFERENCES work_item_nodes(node_id),
    target_ext_id   TEXT REFERENCES external_objects(ext_id),
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT ck_edge_source_xor CHECK (
        (source_node_id IS NOT NULL AND source_ext_id IS NULL) OR
        (source_node_id IS NULL AND source_ext_id IS NOT NULL)
    ),
    CONSTRAINT ck_edge_target_xor CHECK (
        (target_node_id IS NOT NULL AND target_ext_id IS NULL) OR
        (target_node_id IS NULL AND target_ext_id IS NOT NULL)
    )
);
CREATE INDEX IF NOT EXISTS ix_edges_source_node ON edges (source_node_id) WHERE source_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_edges_target_node ON edges (target_node_id) WHERE target_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_edges_source_ext ON edges (source_ext_id) WHERE source_ext_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_edges_target_ext ON edges (target_ext_id) WHERE target_ext_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_edges_relation_type ON edges (relation_type);

-- Retrofit CHECK constraints if table was created by create_all() without them
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_edge_source_xor' AND conrelid = 'edges'::regclass
    ) THEN
        ALTER TABLE edges ADD CONSTRAINT ck_edge_source_xor CHECK (
            (source_node_id IS NOT NULL AND source_ext_id IS NULL) OR
            (source_node_id IS NULL AND source_ext_id IS NOT NULL)
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_edge_target_xor' AND conrelid = 'edges'::regclass
    ) THEN
        ALTER TABLE edges ADD CONSTRAINT ck_edge_target_xor CHECK (
            (target_node_id IS NOT NULL AND target_ext_id IS NULL) OR
            (target_node_id IS NULL AND target_ext_id IS NOT NULL)
        );
    END IF;
END $$;

-- ─── Requests (lightweight tracked work) ─────────────────────────────

CREATE TABLE IF NOT EXISTS requests (
    request_id          TEXT PRIMARY KEY,
    source_system       TEXT NOT NULL,
    source_object_id    TEXT,
    requester           TEXT,
    assigned_agent      TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    urgency             TEXT DEFAULT 'normal',
    summary             TEXT,
    resolution          TEXT,
    promoted_to_case_id TEXT REFERENCES cases(case_id),
    thread_id           TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_requests_status ON requests (status);
CREATE INDEX IF NOT EXISTS ix_requests_assigned_agent ON requests (assigned_agent);
CREATE INDEX IF NOT EXISTS ix_requests_thread_id ON requests (thread_id) WHERE thread_id IS NOT NULL;
