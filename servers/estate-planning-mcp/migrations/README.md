## Estate Planning Migrations

Estate-planning migrations maintain the schema used for entity, document, and planning workflows.

## Why this migration stream exists

StewardOS split finance-heavy tables from estate-core responsibilities. This migration stream keeps estate-planning focused on legal/entity operations.

## Application order

Apply in lexical order:

```bash
psql "$DATABASE_URL" -f migrations/20260228_illiquid_extensions.sql
psql "$DATABASE_URL" -f migrations/20260228_illiquid_breaking_v2.sql
psql "$DATABASE_URL" -f migrations/20260301_estate_core_prune.sql
```

## Notes

- `20260301_estate_core_prune.sql` is intentionally breaking.
- Finance-oriented datasets were moved to `finance-graph`.
- Use `schema.sql` as greenfield baseline.
