-- 001_initial.sql — Postgres DDL for family-office-mail-worker orchestration DB
-- Applies to: orchestration database on personal-db (Postgres 16.6)
-- Run once against a fresh database; SQLAlchemy create_all() handles dev/CI.
-- Tables live in the 'orchestration' schema (matches init-databases.sh provisioning).

SET search_path TO orchestration;

-- ─── Operational tables (queue, idempotency, watch state) ───────────────

CREATE TABLE IF NOT EXISTS email_sessions (
    id              TEXT PRIMARY KEY,
    session_key     TEXT NOT NULL,
    conversation_id TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_email_sessions_session_key ON email_sessions (session_key);

CREATE TABLE IF NOT EXISTS gmail_watch_state (
    email       TEXT PRIMARY KEY,
    history_id  BIGINT NOT NULL,
    expiration  BIGINT,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_gmail_messages (
    message_id      TEXT PRIMARY KEY,
    alias           TEXT NOT NULL,
    thread_id       TEXT,
    sender_email    TEXT,
    status          TEXT NOT NULL,
    sent_message_id TEXT,
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS queued_gmail_notifications (
    id              SERIAL PRIMARY KEY,
    event_key       TEXT NOT NULL UNIQUE,
    payload_json    TEXT NOT NULL,
    email           TEXT,
    history_id      BIGINT,
    status          TEXT NOT NULL,
    attempt_count   INTEGER NOT NULL DEFAULT 0,
    claimed_at      TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_queued_gmail_notifications_event_key ON queued_gmail_notifications (event_key);
CREATE INDEX IF NOT EXISTS ix_queued_gmail_notifications_status ON queued_gmail_notifications (status);

CREATE TABLE IF NOT EXISTS processed_plane_deliveries (
    delivery_id TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ─── Unified orchestration table (replaces pm_sessions + case_snapshots + email_thread_cases) ──

CREATE TABLE IF NOT EXISTS cases (
    case_id             TEXT PRIMARY KEY,
    session_key         TEXT NOT NULL UNIQUE,
    thread_id           TEXT,
    lead_alias          TEXT NOT NULL,
    reply_actor         TEXT,
    workspace_slug      TEXT NOT NULL,
    project_id          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active',
    codex_session_id    TEXT,
    structured_input    JSONB,
    structured_result   JSONB,
    last_human_email_body TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_cases_session_key ON cases (session_key);
CREATE INDEX IF NOT EXISTS ix_cases_thread_id ON cases (thread_id);
CREATE INDEX IF NOT EXISTS ix_cases_status ON cases (status);
