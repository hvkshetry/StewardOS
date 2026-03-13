## Estate Planning Migrations

Apply SQL files in lexical order against the target database.

Example:

```bash
psql "$DATABASE_URL" -f migrations/20260228_illiquid_extensions.sql
psql "$DATABASE_URL" -f migrations/20260228_illiquid_breaking_v2.sql
psql "$DATABASE_URL" -f migrations/20260301_estate_core_prune.sql
psql "$DATABASE_URL" -f migrations/20260303_estate_ops_gap_closure.sql
```

Notes:
- `20260301_estate_core_prune.sql` is intentionally breaking and removes valuation, PL/CFS/BS, XBRL, and OCF tables from estate-planning.
- Those datasets now belong exclusively to `finance-graph`.
- `schema.sql` is the simplified estate-core bootstrap for greenfield installs.
- `20260303_estate_ops_gap_closure.sql` adds comprehensive estate operations tables (succession, fiduciary roles, typed IDs, compliance workflows, provenance) and Paperless-scoped document metadata overlays.
