BEGIN;

-- Baseline bootstrap creates schema `estate`; v2 migration expects it to exist.
SET search_path TO estate;

CREATE TABLE IF NOT EXISTS valuation_methods (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO valuation_methods (code, name, description) VALUES
    ('rentcast_avm', 'RentCast AVM', 'US-only automated residential/land valuation from RentCast'),
    ('manual_comp', 'Manual Comparable Sales', 'User-entered comparable transactions and adjustments'),
    ('manual_mark', 'Manual Mark', 'Direct user mark-to-model or mark-to-market estimate'),
    ('income_approach', 'Income Approach', 'NOI/cap-rate or discounted cash flow from rental stream'),
    ('dcf', 'Discounted Cash Flow', 'Explicit forecast and discount-rate valuation approach')
ON CONFLICT (code) DO NOTHING;

-- Backfill unforeseen historical method codes before attaching FK constraint.
INSERT INTO valuation_methods (code, name, description)
SELECT DISTINCT
    vo.method_code,
    INITCAP(REPLACE(vo.method_code, '_', ' ')),
    'Backfilled from historical valuation_observations'
FROM valuation_observations vo
WHERE vo.method_code IS NOT NULL
  AND BTRIM(vo.method_code) <> ''
ON CONFLICT (code) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'valuation_observations_method_code_fkey'
          AND conrelid = 'estate.valuation_observations'::regclass
    ) THEN
        ALTER TABLE valuation_observations
        ADD CONSTRAINT valuation_observations_method_code_fkey
        FOREIGN KEY (method_code) REFERENCES valuation_methods(code);
    END IF;
END $$;

DO $$
BEGIN
    BEGIN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_assets_jurisdiction ON assets(jurisdiction_id)';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'Skipping idx_assets_jurisdiction creation due to insufficient privilege';
    END;

    BEGIN
        EXECUTE 'CREATE INDEX IF NOT EXISTS idx_asset_taxonomy_country_region ON asset_taxonomy(country_code, region_code)';
    EXCEPTION WHEN insufficient_privilege THEN
        RAISE NOTICE 'Skipping idx_asset_taxonomy_country_region creation due to insufficient privilege';
    END;
END $$;

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

COMMIT;
