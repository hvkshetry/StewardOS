BEGIN;

CREATE SCHEMA IF NOT EXISTS estate;
SET search_path TO estate, public;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM assets
        WHERE num_nonnulls(owner_entity_id, owner_person_id) <> 1
    ) THEN
        RAISE EXCEPTION 'estate.assets must have exactly one owner before applying 20260306_estate_asset_owner_xor.sql';
    END IF;
END
$$;

ALTER TABLE assets
    DROP CONSTRAINT IF EXISTS asset_has_owner;

ALTER TABLE assets
    ADD CONSTRAINT asset_has_owner
    CHECK (num_nonnulls(owner_entity_id, owner_person_id) = 1);

COMMIT;
