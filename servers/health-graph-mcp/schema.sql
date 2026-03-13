BEGIN;

CREATE SCHEMA IF NOT EXISTS health;
SET search_path TO health;

CREATE TABLE IF NOT EXISTS subjects (
    id                  SERIAL PRIMARY KEY,
    display_name        TEXT NOT NULL,
    date_of_birth       DATE,
    sex_at_birth        TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subject_identifiers (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    id_type             TEXT NOT NULL,
    id_value            TEXT NOT NULL,
    source_name         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT subject_identifiers_unique UNIQUE(subject_id, id_type, id_value)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_subject_identifiers_global_unique
    ON subject_identifiers ((upper(btrim(id_type))), (btrim(id_value)));

CREATE TABLE IF NOT EXISTS source_artifacts (
    id                  SERIAL PRIMARY KEY,
    source_name         TEXT NOT NULL,
    artifact_type       TEXT NOT NULL,
    file_path           TEXT,
    sha256              TEXT,
    source_version      TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                  SERIAL PRIMARY KEY,
    source_name         TEXT NOT NULL,
    run_type            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'running',
    rows_read           INTEGER NOT NULL DEFAULT 0,
    rows_written        INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS samples (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    sample_name         TEXT NOT NULL,
    sample_type         TEXT NOT NULL DEFAULT 'dna',
    collected_at        TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT samples_subject_name_unique UNIQUE(subject_id, sample_name)
);

CREATE TABLE IF NOT EXISTS assays (
    id                  SERIAL PRIMARY KEY,
    assay_name          TEXT NOT NULL,
    platform            TEXT,
    assembly            TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS callsets (
    id                  SERIAL PRIMARY KEY,
    sample_id           INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
    assay_id            INTEGER REFERENCES assays(id),
    source_artifact_id  INTEGER REFERENCES source_artifacts(id),
    callset_name        TEXT NOT NULL,
    assembly            TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT callsets_sample_name_unique UNIQUE(sample_id, callset_name)
);

CREATE TABLE IF NOT EXISTS variant_canonical (
    id                  SERIAL PRIMARY KEY,
    variant_key         TEXT NOT NULL UNIQUE,
    vrs_id              TEXT,
    spdi                TEXT,
    rsid                TEXT,
    hgvs_g              TEXT,
    assembly            TEXT,
    chromosome          TEXT,
    position            INTEGER,
    ref                 TEXT,
    alt                 TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS genotype_calls (
    id                  BIGSERIAL PRIMARY KEY,
    callset_id          INTEGER NOT NULL REFERENCES callsets(id) ON DELETE CASCADE,
    variant_id          INTEGER REFERENCES variant_canonical(id),
    rsid                TEXT,
    chromosome          TEXT,
    position            INTEGER,
    genotype            TEXT,
    zygosity            TEXT,
    no_call             BOOLEAN NOT NULL DEFAULT FALSE,
    quality             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS genes (
    id                  SERIAL PRIMARY KEY,
    gene_symbol         TEXT NOT NULL UNIQUE,
    gene_id             TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clinical_assertions (
    id                  SERIAL PRIMARY KEY,
    variant_id          INTEGER REFERENCES variant_canonical(id),
    gene_id             INTEGER REFERENCES genes(id),
    source_name         TEXT NOT NULL,
    source_record_id    TEXT,
    significance        TEXT,
    review_status       TEXT,
    conflict_state      TEXT,
    condition_name      TEXT,
    actionability       TEXT,
    evidence_tier       INTEGER NOT NULL DEFAULT 4,
    action_class        TEXT NOT NULL DEFAULT 'research_only',
    confidence_score    NUMERIC(5,4),
    assertion_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_evaluated      DATE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pgx_haplotypes (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    gene_symbol         TEXT NOT NULL,
    haplotype_label     TEXT NOT NULL,
    function_label      TEXT,
    activity_value      TEXT,
    source_name         TEXT NOT NULL DEFAULT 'pharmcat',
    source_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pgx_diplotypes (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    gene_symbol         TEXT NOT NULL,
    source_diplotype    TEXT,
    recommendation_diplotype TEXT,
    outside_call        BOOLEAN,
    match_score         TEXT,
    source_name         TEXT NOT NULL DEFAULT 'pharmcat',
    source_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pgx_phenotypes (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    gene_symbol         TEXT NOT NULL,
    phenotype           TEXT,
    activity_score      TEXT,
    phenotype_source    TEXT,
    source_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pgx_recommendations (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    gene_symbol         TEXT,
    drug_name           TEXT,
    recommendation_text TEXT NOT NULL,
    source_name         TEXT NOT NULL,
    source_record_id    TEXT,
    evidence_tier       INTEGER NOT NULL DEFAULT 1,
    action_class        TEXT NOT NULL DEFAULT 'actionable_with_guardrails',
    confidence_score    NUMERIC(5,4),
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trait_associations (
    id                  SERIAL PRIMARY KEY,
    variant_id          INTEGER REFERENCES variant_canonical(id),
    source_name         TEXT NOT NULL,
    trait_name          TEXT NOT NULL,
    effect_allele       TEXT,
    effect_size         NUMERIC,
    p_value             NUMERIC,
    ancestry            TEXT,
    study_id            TEXT,
    evidence_tier       INTEGER NOT NULL DEFAULT 3,
    action_class        TEXT NOT NULL DEFAULT 'context_only',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS polygenic_scores (
    id                  SERIAL PRIMARY KEY,
    score_id            TEXT NOT NULL UNIQUE,
    trait_name          TEXT NOT NULL,
    source_name         TEXT NOT NULL DEFAULT 'pgs_catalog',
    ancestry            TEXT,
    license_text        TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS polygenic_evaluations (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    polygenic_score_id  INTEGER NOT NULL REFERENCES polygenic_scores(id) ON DELETE CASCADE,
    score_value         NUMERIC,
    percentile          NUMERIC,
    evidence_tier       INTEGER NOT NULL DEFAULT 3,
    action_class        TEXT NOT NULL DEFAULT 'context_only',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS diagnostic_reports (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    report_id           TEXT,
    status              TEXT,
    code                TEXT,
    effective_at        TIMESTAMPTZ,
    issued_at           TIMESTAMPTZ,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS observations (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    diagnostic_report_id INTEGER REFERENCES diagnostic_reports(id) ON DELETE SET NULL,
    observation_id      TEXT,
    status              TEXT,
    category            TEXT,
    code                TEXT,
    display_name        TEXT,
    value_numeric       NUMERIC,
    value_text          TEXT,
    unit                TEXT,
    effective_at        TIMESTAMPTZ,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverages (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    coverage_id         TEXT,
    status              TEXT,
    payer_name          TEXT,
    plan_name           TEXT,
    member_id           TEXT,
    group_id            TEXT,
    start_date          DATE,
    end_date            DATE,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS insurance_plans (
    id                  SERIAL PRIMARY KEY,
    plan_id             TEXT,
    payer_name          TEXT,
    plan_name           TEXT,
    plan_type           TEXT,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverage_eligibility_requests (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    coverage_id         INTEGER REFERENCES coverages(id) ON DELETE SET NULL,
    request_id          TEXT,
    purpose             TEXT,
    service_code        TEXT,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverage_eligibility_responses (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    coverage_id         INTEGER REFERENCES coverages(id) ON DELETE SET NULL,
    request_id          INTEGER REFERENCES coverage_eligibility_requests(id) ON DELETE SET NULL,
    response_id         TEXT,
    outcome             TEXT,
    inforce             BOOLEAN,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claims (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    coverage_id         INTEGER REFERENCES coverages(id) ON DELETE SET NULL,
    claim_id            TEXT,
    status              TEXT,
    use_type            TEXT,
    priority            TEXT,
    service_code        TEXT,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim_responses (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    claim_id            INTEGER REFERENCES claims(id) ON DELETE SET NULL,
    response_id         TEXT,
    outcome             TEXT,
    disposition         TEXT,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS explanations_of_benefit (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    claim_id            INTEGER REFERENCES claims(id) ON DELETE SET NULL,
    claim_response_id   INTEGER REFERENCES claim_responses(id) ON DELETE SET NULL,
    eob_id              TEXT,
    status              TEXT,
    outcome             TEXT,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prior_auth_events (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    claim_id            INTEGER REFERENCES claims(id) ON DELETE SET NULL,
    prior_auth_ref      TEXT,
    status              TEXT,
    decision            TEXT,
    source_name         TEXT,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverage_code_maps (
    id                  SERIAL PRIMARY KEY,
    code_system         TEXT NOT NULL,
    code_value          TEXT NOT NULL,
    code_display        TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT coverage_code_maps_unique UNIQUE(code_system, code_value)
);

CREATE TABLE IF NOT EXISTS benefit_rules (
    id                  SERIAL PRIMARY KEY,
    payer_name          TEXT,
    plan_name           TEXT,
    code_system         TEXT NOT NULL,
    code_value          TEXT NOT NULL,
    rule_type           TEXT NOT NULL DEFAULT 'coverage',
    decision_default    TEXT NOT NULL,
    requires_prior_auth BOOLEAN NOT NULL DEFAULT FALSE,
    notes               TEXT,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverage_determinations (
    id                  SERIAL PRIMARY KEY,
    subject_id          INTEGER REFERENCES subjects(id),
    coverage_id         INTEGER REFERENCES coverages(id) ON DELETE SET NULL,
    code_system         TEXT,
    code_value          TEXT,
    decision            TEXT NOT NULL,
    required_prior_auth BOOLEAN NOT NULL DEFAULT FALSE,
    reason_codes        JSONB NOT NULL DEFAULT '[]'::jsonb,
    explanation         TEXT,
    supporting_refs     JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_metadata (
    id                  SERIAL PRIMARY KEY,
    paperless_doc_id    INTEGER NOT NULL UNIQUE,
    title               TEXT,
    doc_type            TEXT,
    created_date        DATE,
    source_snapshot     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_links (
    id                  SERIAL PRIMARY KEY,
    paperless_doc_id    INTEGER NOT NULL REFERENCES document_metadata(paperless_doc_id) ON DELETE CASCADE,
    subject_id          INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
    record_type         TEXT NOT NULL,
    record_id           TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS literature_evidence (
    id                  SERIAL PRIMARY KEY,
    source_name         TEXT NOT NULL,
    external_id         TEXT,
    title               TEXT,
    url                 TEXT,
    published_at        DATE,
    abstract_text       TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_links (
    id                  SERIAL PRIMARY KEY,
    literature_evidence_id INTEGER NOT NULL REFERENCES literature_evidence(id) ON DELETE CASCADE,
    assertion_id        INTEGER REFERENCES clinical_assertions(id) ON DELETE CASCADE,
    variant_id          INTEGER REFERENCES variant_canonical(id) ON DELETE CASCADE,
    trait_association_id INTEGER REFERENCES trait_associations(id) ON DELETE CASCADE,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence_tiers (
    tier                INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_classes (
    action_class        TEXT PRIMARY KEY,
    description         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_policy_rules (
    id                  SERIAL PRIMARY KEY,
    evidence_tier       INTEGER NOT NULL,
    action_class        TEXT NOT NULL,
    allow_direct_action BOOLEAN NOT NULL,
    research_mode_only  BOOLEAN NOT NULL,
    notes               TEXT,
    CONSTRAINT recommendation_policy_unique UNIQUE(evidence_tier, action_class)
);

INSERT INTO evidence_tiers (tier, name, description) VALUES
    (1, 'guideline_backed', 'Guideline-backed pharmacogenomics recommendations'),
    (2, 'clinically_curated', 'Curated clinical genetics with expert review status'),
    (3, 'association_context', 'Replicated association context and polygenic signals'),
    (4, 'exploratory', 'Literature-mined or low-confidence exploratory evidence')
ON CONFLICT (tier) DO NOTHING;

INSERT INTO action_classes (action_class, description) VALUES
    ('actionable_with_guardrails', 'User-facing action with safety and medical caveats'),
    ('review_required', 'Action requires clinician or care coordinator review'),
    ('context_only', 'Provide context only, no direct recommendation'),
    ('research_only', 'Exploratory signal for hypothesis and self-experiment notes only')
ON CONFLICT (action_class) DO NOTHING;

INSERT INTO recommendation_policy_rules (evidence_tier, action_class, allow_direct_action, research_mode_only, notes) VALUES
    (1, 'actionable_with_guardrails', TRUE, FALSE, 'PGx and high-confidence guideline actions'),
    (2, 'review_required', FALSE, FALSE, 'Curated clinical assertions require review'),
    (3, 'context_only', FALSE, FALSE, 'Risk context only'),
    (4, 'research_only', FALSE, TRUE, 'No direct action allowed')
ON CONFLICT (evidence_tier, action_class) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_genotype_calls_callset ON genotype_calls(callset_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_assays_name_platform_unique
    ON assays(assay_name, COALESCE(platform, ''));
CREATE UNIQUE INDEX IF NOT EXISTS idx_genotype_calls_callset_variant_unique
    ON genotype_calls(callset_id, chromosome, position, COALESCE(rsid, ''));
CREATE INDEX IF NOT EXISTS idx_genotype_calls_chr_pos ON genotype_calls(chromosome, position);
CREATE INDEX IF NOT EXISTS idx_variant_canonical_rsid ON variant_canonical(rsid);
CREATE INDEX IF NOT EXISTS idx_clinical_assertions_variant ON clinical_assertions(variant_id);
CREATE INDEX IF NOT EXISTS idx_pgx_recommendations_subject ON pgx_recommendations(subject_id);
CREATE INDEX IF NOT EXISTS idx_observations_subject_code ON observations(subject_id, code);
CREATE INDEX IF NOT EXISTS idx_coverages_subject ON coverages(subject_id);
CREATE INDEX IF NOT EXISTS idx_coverage_determinations_subject ON coverage_determinations(subject_id);
CREATE INDEX IF NOT EXISTS idx_document_links_doc ON document_links(paperless_doc_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_literature_evidence_source_external_unique
    ON literature_evidence(source_name, COALESCE(external_id, ''));
CREATE INDEX IF NOT EXISTS idx_literature_evidence_source ON literature_evidence(source_name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pgx_diplotypes_dedupe
    ON pgx_diplotypes(
        subject_id,
        gene_symbol,
        source_name,
        COALESCE(source_diplotype, ''),
        COALESCE(recommendation_diplotype, '')
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_pgx_phenotypes_dedupe
    ON pgx_phenotypes(
        subject_id,
        gene_symbol,
        COALESCE(phenotype, ''),
        COALESCE(activity_score, ''),
        COALESCE(phenotype_source, '')
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_pgx_recommendations_dedupe
    ON pgx_recommendations(
        subject_id,
        COALESCE(gene_symbol, ''),
        COALESCE(drug_name, ''),
        source_name,
        COALESCE(source_record_id, ''),
        recommendation_text
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_clinical_assertions_dedupe
    ON clinical_assertions(
        COALESCE(variant_id, 0),
        COALESCE(gene_id, 0),
        source_name,
        COALESCE(source_record_id, ''),
        COALESCE(condition_name, ''),
        COALESCE(significance, '')
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_trait_associations_dedupe
    ON trait_associations(
        COALESCE(variant_id, 0),
        source_name,
        trait_name,
        COALESCE(study_id, ''),
        COALESCE(effect_allele, '')
    );
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_links_dedupe
    ON evidence_links(
        literature_evidence_id,
        COALESCE(assertion_id, 0),
        COALESCE(variant_id, 0),
        COALESCE(trait_association_id, 0),
        COALESCE(notes, '')
    );

COMMIT;
