## Health Graph Migrations

Apply SQL files in lexical order against the target database.

Example:

```bash
psql "$DATABASE_URL" -f schema.sql
psql "$DATABASE_URL" -f migrations/20260305_health_graph_init.sql
psql "$DATABASE_URL" -f migrations/20260305_hydration_idempotency.sql
```

Notes:
- Migrations are idempotent where possible.
- `schema.sql` is the full bootstrap script for greenfield installs.
- On existing environments, apply migrations in lexical order.
