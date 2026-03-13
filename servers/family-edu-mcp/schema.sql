CREATE SCHEMA IF NOT EXISTS family_edu;
SET search_path TO family_edu, public;

CREATE TABLE IF NOT EXISTS learners (
    id BIGSERIAL PRIMARY KEY,
    display_name TEXT NOT NULL,
    date_of_birth DATE NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (display_name, date_of_birth)
);

CREATE TABLE IF NOT EXISTS guardian_relationships (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    guardian_name TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS institutions (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    institution_type TEXT NOT NULL DEFAULT 'school',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS programs (
    id BIGSERIAL PRIMARY KEY,
    institution_id BIGINT REFERENCES institutions(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    program_type TEXT NOT NULL DEFAULT 'general',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (institution_id, name)
);

CREATE TABLE IF NOT EXISTS academic_years (
    id BIGSERIAL PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    start_date DATE,
    end_date DATE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS terms (
    id BIGSERIAL PRIMARY KEY,
    academic_year_id BIGINT REFERENCES academic_years(id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (academic_year_id, label)
);

CREATE TABLE IF NOT EXISTS staff_contacts (
    id BIGSERIAL PRIMARY KEY,
    institution_id BIGINT REFERENCES institutions(id) ON DELETE SET NULL,
    program_id BIGINT REFERENCES programs(id) ON DELETE SET NULL,
    full_name TEXT NOT NULL,
    role TEXT,
    email TEXT,
    phone TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS enrollments (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    institution_id BIGINT REFERENCES institutions(id) ON DELETE SET NULL,
    program_id BIGINT REFERENCES programs(id) ON DELETE SET NULL,
    academic_year_id BIGINT REFERENCES academic_years(id) ON DELETE SET NULL,
    term_id BIGINT REFERENCES terms(id) ON DELETE SET NULL,
    staff_contact_id BIGINT REFERENCES staff_contacts(id) ON DELETE SET NULL,
    enrollment_status TEXT NOT NULL DEFAULT 'active',
    start_date DATE,
    end_date DATE,
    notes TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    source_system TEXT NOT NULL DEFAULT 'paperless',
    paperless_document_id BIGINT,
    institution_id BIGINT REFERENCES institutions(id) ON DELETE SET NULL,
    program_id BIGINT REFERENCES programs(id) ON DELETE SET NULL,
    term_id BIGINT REFERENCES terms(id) ON DELETE SET NULL,
    document_date DATE,
    review_status TEXT NOT NULL DEFAULT 'pending',
    title TEXT,
    summary TEXT,
    artifact_link TEXT,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
DECLARE
    has_constraint BOOLEAN;
    idx_oid OID;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ux_artifacts_source_document'
          AND conrelid = 'artifacts'::regclass
    ) INTO has_constraint;

    SELECT to_regclass('family_edu.ux_artifacts_source_document') INTO idx_oid;

    IF idx_oid IS NOT NULL AND NOT has_constraint THEN
        EXECUTE 'DROP INDEX family_edu.ux_artifacts_source_document';
    END IF;

    IF NOT has_constraint THEN
        ALTER TABLE artifacts
            ADD CONSTRAINT ux_artifacts_source_document
            UNIQUE (source_system, paperless_document_id);
    END IF;
END$$;

CREATE TABLE IF NOT EXISTS artifact_links (
    id BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL,
    record_id BIGINT NOT NULL,
    relation_type TEXT NOT NULL DEFAULT 'evidence',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifact_extracts (
    id BIGSERIAL PRIMARY KEY,
    artifact_id BIGINT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    parser_version TEXT NOT NULL,
    confidence NUMERIC(5,4),
    extraction_status TEXT NOT NULL DEFAULT 'draft',
    extracted_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_text TEXT,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS artifact_reviews (
    id BIGSERIAL PRIMARY KEY,
    artifact_extract_id BIGINT NOT NULL REFERENCES artifact_extracts(id) ON DELETE CASCADE,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    corrections JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_notes TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assessment_definitions (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    subject_area TEXT,
    measure_type TEXT NOT NULL DEFAULT 'numeric',
    unit TEXT,
    benchmark JSONB NOT NULL DEFAULT '{}'::jsonb,
    higher_is_better BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assessment_events (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    assessment_definition_id BIGINT NOT NULL REFERENCES assessment_definitions(id) ON DELETE RESTRICT,
    assessed_on DATE NOT NULL,
    institution_id BIGINT REFERENCES institutions(id) ON DELETE SET NULL,
    program_id BIGINT REFERENCES programs(id) ON DELETE SET NULL,
    term_id BIGINT REFERENCES terms(id) ON DELETE SET NULL,
    staff_contact_id BIGINT REFERENCES staff_contacts(id) ON DELETE SET NULL,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    event_notes TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assessment_results (
    id BIGSERIAL PRIMARY KEY,
    assessment_event_id BIGINT NOT NULL REFERENCES assessment_events(id) ON DELETE CASCADE,
    result_numeric NUMERIC,
    result_text TEXT,
    result_boolean BOOLEAN,
    percentile NUMERIC(5,2),
    proficiency_band TEXT,
    normalized_score NUMERIC,
    rubric_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS report_card_facts (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    term_id BIGINT REFERENCES terms(id) ON DELETE SET NULL,
    subject TEXT NOT NULL,
    grade_mark TEXT,
    teacher_comment TEXT,
    teacher_name TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    issued_on DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (learner_id, term_id, subject, issued_on)
);

CREATE TABLE IF NOT EXISTS attendance_facts (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    term_id BIGINT REFERENCES terms(id) ON DELETE SET NULL,
    attendance_date DATE NOT NULL,
    status TEXT NOT NULL,
    minutes_absent INTEGER,
    notes TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS support_plans (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    plan_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    start_date DATE,
    end_date DATE,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS activity_definitions (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    activity_type TEXT NOT NULL DEFAULT 'general',
    default_unit TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS seasons (
    id BIGSERIAL PRIMARY KEY,
    activity_definition_id BIGINT REFERENCES activity_definitions(id) ON DELETE SET NULL,
    label TEXT NOT NULL,
    start_date DATE,
    end_date DATE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (activity_definition_id, label)
);

CREATE TABLE IF NOT EXISTS activity_sessions (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    activity_definition_id BIGINT REFERENCES activity_definitions(id) ON DELETE SET NULL,
    season_id BIGINT REFERENCES seasons(id) ON DELETE SET NULL,
    institution_id BIGINT REFERENCES institutions(id) ON DELETE SET NULL,
    program_id BIGINT REFERENCES programs(id) ON DELETE SET NULL,
    term_id BIGINT REFERENCES terms(id) ON DELETE SET NULL,
    staff_contact_id BIGINT REFERENCES staff_contacts(id) ON DELETE SET NULL,
    session_date DATE,
    duration_minutes INTEGER,
    notes TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS metric_definitions (
    id BIGSERIAL PRIMARY KEY,
    activity_definition_id BIGINT REFERENCES activity_definitions(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT,
    polarity TEXT NOT NULL DEFAULT 'higher_is_better',
    measure_type TEXT NOT NULL DEFAULT 'numeric',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (activity_definition_id, code)
);

CREATE TABLE IF NOT EXISTS metric_observations (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    metric_definition_id BIGINT NOT NULL REFERENCES metric_definitions(id) ON DELETE RESTRICT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    value_numeric NUMERIC,
    value_text TEXT,
    value_boolean BOOLEAN,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    recorded_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rubric_definitions (
    id BIGSERIAL PRIMARY KEY,
    activity_definition_id BIGINT REFERENCES activity_definitions(id) ON DELETE SET NULL,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rubric_scores (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    rubric_definition_id BIGINT NOT NULL REFERENCES rubric_definitions(id) ON DELETE RESTRICT,
    scored_on DATE,
    score_numeric NUMERIC,
    score_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS awards_or_certificates (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    issuer TEXT,
    awarded_on DATE,
    description TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS goals (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    goal_type TEXT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    target_date DATE,
    success_criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    owner TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS goal_progress (
    id BIGSERIAL PRIMARY KEY,
    goal_id BIGINT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
    progress_date DATE NOT NULL DEFAULT CURRENT_DATE,
    progress_value NUMERIC,
    status TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS action_items (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    goal_id BIGINT REFERENCES goals(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    due_date DATE,
    priority TEXT NOT NULL DEFAULT 'medium',
    owner TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS weekly_plans (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    week_start DATE NOT NULL,
    plan_type TEXT NOT NULL DEFAULT 'activity',
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (learner_id, week_start, plan_type)
);

CREATE TABLE IF NOT EXISTS activity_catalog (
    id BIGSERIAL PRIMARY KEY,
    builtin_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    min_age_months INTEGER NOT NULL DEFAULT 0,
    max_age_months INTEGER NOT NULL DEFAULT 216,
    category TEXT NOT NULL DEFAULT 'general',
    duration_minutes INTEGER NOT NULL DEFAULT 30,
    indoor_outdoor TEXT NOT NULL DEFAULT 'both',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS weekly_plan_items (
    id BIGSERIAL PRIMARY KEY,
    weekly_plan_id BIGINT NOT NULL REFERENCES weekly_plans(id) ON DELETE CASCADE,
    day_of_week TEXT NOT NULL,
    activity_catalog_id BIGINT REFERENCES activity_catalog(id) ON DELETE SET NULL,
    activity_definition_id BIGINT REFERENCES activity_definitions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    scheduled_time TEXT,
    duration_minutes INTEGER,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS observations (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    observed_on DATE NOT NULL DEFAULT CURRENT_DATE,
    domain TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    observation_text TEXT NOT NULL,
    sentiment TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    recorded_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
    title TEXT,
    entry_text TEXT NOT NULL,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comment_threads (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    parent_record_type TEXT NOT NULL,
    parent_record_id BIGINT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comments (
    id BIGSERIAL PRIMARY KEY,
    thread_id BIGINT NOT NULL REFERENCES comment_threads(id) ON DELETE CASCADE,
    comment_text TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS milestone_definitions (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    expected_age_months INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learner_milestone_status (
    id BIGSERIAL PRIMARY KEY,
    learner_id BIGINT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    milestone_definition_id BIGINT NOT NULL REFERENCES milestone_definitions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    achieved_date DATE,
    notes TEXT,
    source_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (learner_id, milestone_definition_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_learner_status
    ON enrollments(learner_id, enrollment_status);

CREATE INDEX IF NOT EXISTS idx_artifacts_learner_date
    ON artifacts(learner_id, document_date DESC);

CREATE INDEX IF NOT EXISTS idx_artifacts_review_status
    ON artifacts(review_status);

CREATE INDEX IF NOT EXISTS idx_artifact_extracts_artifact
    ON artifact_extracts(artifact_id, extracted_at DESC);

CREATE INDEX IF NOT EXISTS idx_assessment_events_learner_date
    ON assessment_events(learner_id, assessed_on DESC);

CREATE INDEX IF NOT EXISTS idx_metric_observations_learner_observed
    ON metric_observations(learner_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_goals_learner_status
    ON goals(learner_id, status);

CREATE INDEX IF NOT EXISTS idx_action_items_learner_status_due
    ON action_items(learner_id, status, due_date);

CREATE INDEX IF NOT EXISTS idx_weekly_plans_learner_week
    ON weekly_plans(learner_id, week_start DESC);

CREATE INDEX IF NOT EXISTS idx_observations_learner_date
    ON observations(learner_id, observed_on DESC);

CREATE INDEX IF NOT EXISTS idx_journal_entries_learner_date
    ON journal_entries(learner_id, entry_date DESC);

CREATE INDEX IF NOT EXISTS idx_learner_milestone_status_learner_status
    ON learner_milestone_status(learner_id, status);

CREATE INDEX IF NOT EXISTS idx_activity_catalog_age_range
    ON activity_catalog(min_age_months, max_age_months);
