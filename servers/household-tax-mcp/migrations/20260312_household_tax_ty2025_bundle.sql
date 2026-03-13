BEGIN;

SET search_path TO tax;

INSERT INTO authority_bundles(
    bundle_version,
    tax_year,
    jurisdictions,
    federal_individual_kernel,
    federal_fiduciary_kernel,
    massachusetts_kernel
)
VALUES (
    'us_ma_2025_v1',
    2025,
    '["US","MA"]'::jsonb,
    'taxcalc_2025',
    'builtin_2025_fiduciary_kernel',
    'builtin_2025_ma_kernel'
)
ON CONFLICT (bundle_version) DO NOTHING;

COMMIT;
