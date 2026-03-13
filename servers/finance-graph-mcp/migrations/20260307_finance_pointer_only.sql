BEGIN;

SET search_path TO finance, public;

WITH ranked_observations AS (
    SELECT
        vo.asset_id,
        vo.id AS observation_id,
        row_number() OVER (
            PARTITION BY vo.asset_id
            ORDER BY vo.valuation_date DESC, vo.confidence_score DESC NULLS LAST, vo.id DESC
        ) AS rank_order
    FROM valuation_observations vo
),
best_observations AS (
    SELECT asset_id, observation_id
    FROM ranked_observations
    WHERE rank_order = 1
)
UPDATE assets a
SET current_valuation_observation_id = bo.observation_id,
    updated_at = now()
FROM best_observations bo
WHERE a.id = bo.asset_id
  AND a.current_valuation_observation_id IS DISTINCT FROM bo.observation_id;

ALTER TABLE assets DROP COLUMN IF EXISTS current_valuation_amount;
ALTER TABLE assets DROP COLUMN IF EXISTS valuation_currency;
ALTER TABLE assets DROP COLUMN IF EXISTS valuation_date;

COMMIT;
