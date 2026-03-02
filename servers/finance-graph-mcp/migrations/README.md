## Finance Graph Migrations

These migrations evolve the finance graph schema used for valuation, liability, and financial state workflows.

## Why this migration stream exists

Finance workflows need frequent schema iteration for new instrument/asset/liability coverage while preserving deterministic query behavior.

## Application order

Apply in lexical order:

```bash
psql "$DATABASE_URL" -f migrations/20260228_illiquid_extensions.sql
psql "$DATABASE_URL" -f migrations/20260228_illiquid_breaking_v2.sql
psql "$DATABASE_URL" -f migrations/20260301_liability_graph.sql
```

## Notes

- `schema.sql` is the greenfield bootstrap script.
- Migrations are idempotent where practical.
- Validate downstream queries after breaking migration updates.
