BEGIN;

CREATE SCHEMA IF NOT EXISTS finance;
SET search_path TO finance, public;

ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS current_valuation_observation_id INTEGER;

WITH legacy_assets AS (
    SELECT a.id AS asset_id,
           a.current_valuation_amount AS value_amount,
           COALESCE(NULLIF(btrim(a.valuation_currency), ''), 'USD') AS value_currency,
           COALESCE(a.valuation_date, CURRENT_DATE) AS valuation_date
    FROM assets a
    WHERE a.current_valuation_observation_id IS NULL
      AND a.current_valuation_amount IS NOT NULL
), inserted_legacy_observations AS (
    INSERT INTO valuation_observations (
        asset_id,
        method_code,
        source,
        value_amount,
        value_currency,
        valuation_date,
        confidence_score,
        notes,
        evidence
    )
    SELECT la.asset_id,
           'manual_mark',
           'legacy_asset_cache',
           la.value_amount,
           la.value_currency,
           la.valuation_date,
           0.1000,
           'Backfilled from pre-cutover asset valuation cache',
           jsonb_build_object('migration', '20260307_finance_hard_cutover')
    FROM legacy_assets la
    WHERE NOT EXISTS (
        SELECT 1
        FROM valuation_observations vo
        WHERE vo.asset_id = la.asset_id
          AND vo.source = 'legacy_asset_cache'
          AND vo.method_code = 'manual_mark'
          AND vo.value_amount = la.value_amount
          AND vo.value_currency = la.value_currency
          AND vo.valuation_date = la.valuation_date
    )
    RETURNING id
)
SELECT COUNT(*) FROM inserted_legacy_observations;

UPDATE assets a
SET current_valuation_observation_id = NULL
WHERE current_valuation_observation_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM valuation_observations vo
      WHERE vo.id = a.current_valuation_observation_id
  );

WITH ranked_observations AS (
    SELECT vo.id,
           vo.asset_id,
           ROW_NUMBER() OVER (
               PARTITION BY vo.asset_id
               ORDER BY vo.valuation_date DESC, vo.confidence_score DESC NULLS LAST, vo.id DESC
           ) AS rank_order
    FROM valuation_observations vo
),
best_observations AS (
    SELECT ro.asset_id, ro.id AS observation_id
    FROM ranked_observations ro
    WHERE ro.rank_order = 1
)
UPDATE assets a
SET current_valuation_observation_id = bo.observation_id,
    current_valuation_amount = vo.value_amount,
    valuation_currency = vo.value_currency,
    valuation_date = vo.valuation_date,
    updated_at = now()
FROM best_observations bo
JOIN valuation_observations vo ON vo.id = bo.observation_id
WHERE a.id = bo.asset_id
  AND (
      a.current_valuation_observation_id IS DISTINCT FROM bo.observation_id
      OR a.current_valuation_amount IS DISTINCT FROM vo.value_amount
      OR a.valuation_currency IS DISTINCT FROM vo.value_currency
      OR a.valuation_date IS DISTINCT FROM vo.valuation_date
  );

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'assets_current_valuation_observation_fk'
          AND conrelid = 'assets'::regclass
    ) THEN
        ALTER TABLE assets
            ADD CONSTRAINT assets_current_valuation_observation_fk
            FOREIGN KEY (current_valuation_observation_id)
            REFERENCES valuation_observations(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_assets_current_valuation_observation
    ON assets (current_valuation_observation_id);

COMMENT ON COLUMN assets.current_valuation_amount IS
    'Denormalized projection of current_valuation_observation_id for internal maintenance; do not read or update directly.';
COMMENT ON COLUMN assets.valuation_currency IS
    'Denormalized projection of current_valuation_observation_id currency for internal maintenance; do not read or update directly.';
COMMENT ON COLUMN assets.valuation_date IS
    'Denormalized projection of current_valuation_observation_id date for internal maintenance; do not read or update directly.';

ALTER TABLE xbrl_facts
    ADD COLUMN IF NOT EXISTS fact_fingerprint TEXT;

WITH fact_seed AS (
    SELECT xf.id,
           md5(
               concat_ws(
                   '|',
                   COALESCE(xc.concept_qname, ''),
                   COALESCE(xctx.context_ref, ''),
                   COALESCE(xu.unit_ref, ''),
                   COALESCE(xctx.period_start::text, ''),
                   COALESCE(xctx.period_end::text, ''),
                   COALESCE(xctx.instant_date::text, ''),
                   COALESCE(xf.fact_value_text, ''),
                   COALESCE(xf.fact_value_numeric::text, ''),
                   COALESCE(xf.decimals, ''),
                   COALESCE(xf.precision, ''),
                   COALESCE(xctx.dimensions::text, '{}'),
                   COALESCE(xf.metadata::text, '{}')
               )
           ) AS fact_fingerprint
    FROM xbrl_facts xf
    JOIN xbrl_concepts xc ON xc.id = xf.concept_id
    LEFT JOIN xbrl_contexts xctx ON xctx.id = xf.context_id
    LEFT JOIN xbrl_units xu ON xu.id = xf.unit_id
    WHERE xf.fact_fingerprint IS NULL OR btrim(xf.fact_fingerprint) = ''
)
UPDATE xbrl_facts xf
SET fact_fingerprint = fs.fact_fingerprint
FROM fact_seed fs
WHERE xf.id = fs.id;

DELETE FROM xbrl_facts xf
USING xbrl_facts duplicate
WHERE xf.id > duplicate.id
  AND xf.xbrl_report_id = duplicate.xbrl_report_id
  AND xf.fact_fingerprint = duplicate.fact_fingerprint;

ALTER TABLE xbrl_facts
    ALTER COLUMN fact_fingerprint SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'xbrl_fact_unique'
          AND conrelid = 'xbrl_facts'::regclass
    ) THEN
        ALTER TABLE xbrl_facts
            ADD CONSTRAINT xbrl_fact_unique UNIQUE (xbrl_report_id, fact_fingerprint);
    END IF;
END
$$;

ALTER TABLE liability_payments
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

UPDATE liability_payments
SET idempotency_key = 'legacy:' || id::text
WHERE idempotency_key IS NULL OR btrim(idempotency_key) = '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'liability_payments_idempotency_key_key'
          AND conrelid = 'liability_payments'::regclass
    ) THEN
        ALTER TABLE liability_payments
            ADD CONSTRAINT liability_payments_idempotency_key_key UNIQUE (idempotency_key);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'liability_payments_amount_total_nonnegative'
          AND conrelid = 'liability_payments'::regclass
    ) THEN
        ALTER TABLE liability_payments
            ADD CONSTRAINT liability_payments_amount_total_nonnegative
            CHECK (amount_total >= 0);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'liability_payments_amount_principal_nonnegative'
          AND conrelid = 'liability_payments'::regclass
    ) THEN
        ALTER TABLE liability_payments
            ADD CONSTRAINT liability_payments_amount_principal_nonnegative
            CHECK (amount_principal IS NULL OR amount_principal >= 0);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'liability_payments_amount_interest_nonnegative'
          AND conrelid = 'liability_payments'::regclass
    ) THEN
        ALTER TABLE liability_payments
            ADD CONSTRAINT liability_payments_amount_interest_nonnegative
            CHECK (amount_interest IS NULL OR amount_interest >= 0);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'liability_payments_amount_escrow_nonnegative'
          AND conrelid = 'liability_payments'::regclass
    ) THEN
        ALTER TABLE liability_payments
            ADD CONSTRAINT liability_payments_amount_escrow_nonnegative
            CHECK (amount_escrow IS NULL OR amount_escrow >= 0);
    END IF;
END
$$;

CREATE OR REPLACE VIEW v_net_worth_by_jurisdiction AS
SELECT
    j.code AS jurisdiction_code,
    j.name AS jurisdiction_name,
    j.country,
    cvo.value_currency AS currency,
    SUM(cvo.value_amount) AS total_value,
    COUNT(*) AS asset_count
FROM assets a
LEFT JOIN valuation_observations cvo ON cvo.id = a.current_valuation_observation_id
JOIN jurisdictions j ON a.jurisdiction_id = j.id
WHERE cvo.value_amount IS NOT NULL
GROUP BY j.code, j.name, j.country, cvo.value_currency;

COMMIT;
