BEGIN;

CREATE SCHEMA IF NOT EXISTS health;
SET search_path TO health, public;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM subject_identifiers
        GROUP BY upper(btrim(id_type)), btrim(id_value)
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'health.subject_identifiers has duplicate normalized identifier values; reconcile them before applying 20260306_subject_identifier_global_uniqueness.sql';
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_subject_identifiers_global_unique
    ON subject_identifiers ((upper(btrim(id_type))), (btrim(id_value)));

COMMIT;
