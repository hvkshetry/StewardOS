## Finance Graph Migrations

Apply SQL files in lexical order against the target database.

Example:

```bash
psql "$DATABASE_URL" -f migrations/20260228_illiquid_extensions.sql
psql "$DATABASE_URL" -f migrations/20260228_illiquid_breaking_v2.sql
psql "$DATABASE_URL" -f migrations/20260301_liability_graph.sql
```

Notes:
- Migrations are idempotent (`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`) where possible.
- `schema.sql` remains the full bootstrap script for greenfield installs.
- Apply `schema.sql` first on empty databases; follow with migrations in lexical order.
