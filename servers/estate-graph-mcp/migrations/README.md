## Estate Graph Migrations

These migrations evolve the estate graph schema used by StewardOS estate workflows.

## Why these migrations matter

Estate data has long-lived entities and relationship paths. Schema drift must be controlled so ownership and compliance logic stay reliable.

## Application order

Apply SQL files in lexical order against the target database.

Example:

```bash
psql "$DATABASE_URL" -f migrations/20260228_illiquid_extensions.sql
psql "$DATABASE_URL" -f migrations/20260228_illiquid_breaking_v2.sql
```

## Notes

- Prefer running `schema.sql` first on greenfield installs.
- Migrations are idempotent where possible (`IF NOT EXISTS`, `ON CONFLICT`).
- Review breaking migrations before production application.
