# Self-Hosted Software

StewardOS runs a consolidated local software stack via Docker Compose on a dedicated home server.

## Platform Services

### Infrastructure

- **PostgreSQL 16.6** (`personal-db`) — shared by Paperless, Ghostfolio, wger, family-edu-mcp, and other DB-backed MCP servers
- **Redis 7** (`personal-redis`) — shared by Paperless and Ghostfolio

### Document & Knowledge Management

- **Paperless-ngx** (2.20.7) — document management with OCR and tagging
- **Memos** — notes and knowledge capture
- **Vaultwarden** (1.35.2) — password management

### Financial

- **Actual Budget** — budgeting and cash flow
- **Ghostfolio** — portfolio tracking and performance analytics

### Household Operations

- **Mealie** — meal planning and recipes
- **Grocy** — pantry inventory and shopping lists
- **Homebox** — home inventory tracking
- **wger** — workout and nutrition tracking

### Project Management (Plane Stack)

Plane provides the single source of truth for task delegation across all 8 personas:

- **plane-api** — REST API server
- **plane-worker** — background task processing
- **plane-beat-worker** — scheduled task runner
- **plane-migrator** — database migrations
- **plane-admin** — admin interface
- **plane-space** — public-facing spaces
- **plane-live** — real-time collaboration
- **plane-web** — web frontend
- **plane-db** (Postgres 15) — dedicated Plane database
- **plane-redis** (Valkey 8) — dedicated Plane cache/queue
- **plane-minio** — S3-compatible object storage for Plane

See [Plane Workspaces](../../services/plane/WORKSPACES.md) for the 7-workspace domain taxonomy.

## Runtime Characteristics

- services are loopback-bound by default,
- health checks are defined for critical services,
- resource limits are explicitly set in compose definitions,
- external exposure is through Cloudflare tunnel to selected services.

## Operational Notes

- service-specific credentials are configured via local `.env` files (gitignored),
- public templates are provided via `services/.env.example` and `services/plane/env.template`,
- backup and retention strategy is documented in `services/backup-personal.sh`,
- database initialization handled by `services/personal-db/init-databases.sh`.

## Infrastructure Changes (March 2026)

- **Added:** Full Plane stack (12 containers + dedicated Valkey)
- **Removed:** n8n (workflow automation), Directus (data studio), changedetection.io (web monitoring) — all superseded by Plane-based task management and agent-driven automation
