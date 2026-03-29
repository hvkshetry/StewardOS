# Self-Hosted Software

StewardOS runs on a self-hosted OSS application stack defined in [`services/docker-compose.yml`](../../../services/docker-compose.yml).

## Why this exists

This layer is the operational substrate for everything else in StewardOS:

- It hosts the systems of record (documents, budgets, portfolio state, inventory, notes).
- It gives MCP servers stable local targets to integrate against.
- It keeps critical household/family-office workflows portable and auditable on your own infrastructure.

Without this layer, personas can still generate text, but they cannot reliably read or update real operating state.

## What is currently configured

Compose currently provisions a loopback-first stack with explicit healthchecks, resource limits, and env-driven secrets via [`services/.env.example`](../../../services/.env.example).

### Tier 1: Core Infrastructure

Shared data plane services that other applications depend on.

| Service | Image | Dependents | Description |
|---------|-------|------------|-------------|
| `personal-db` | PostgreSQL 16 | Paperless-ngx, Ghostfolio, wger, Plane, finance-graph-mcp, estate-planning-mcp, health-graph-mcp, household-tax-mcp, family-edu-mcp, ontology-mcp | Shared relational database — consolidated `stewardos_db` with `core`, `finance`, `estate`, `health`, `tax`, `family_edu`, `orchestration` schemas |
| `personal-redis` | Redis 7 | Paperless-ngx, Ghostfolio, wger | Cache/queue backend |

### Tier 2: Application Services

Domain-specific applications that serve as systems of record, each exposed to personas through MCP servers.

| Service | Image | Depends On | MCP Server | Description |
|---------|-------|------------|------------|-------------|
| `paperless-ngx` | Paperless-ngx 2.20 | PostgreSQL, Redis | `paperless-mcp`, `health-graph-mcp` | Document ingestion, OCR, tagging, retrieval |
| `ghostfolio` | Ghostfolio 2.243 | PostgreSQL, Redis | `ghostfolio-mcp`, `portfolio-analytics` | Portfolio tracking and holdings context |
| `actual-budget` | Actual Server 26.2 | — | `actual-mcp` | Household budgeting and transaction ledger |
| `mealie` | Mealie v3.11 | — | `mealie-mcp-server` | Recipes and weekly meal planning |
| `grocy` | Grocy 4.5 | — | `grocy-mcp` | Pantry and consumable inventory |
| `wger-web` + celery + nginx | wger 2.3-dev | PostgreSQL, Redis | `wger-mcp` | Fitness and nutrition tracking |
| `homebox` | Homebox 0.23 | — | `homebox-mcp` | Household asset/inventory tracking |
| `memos` | Memos 0.26 | — | `memos-mcp` | Quick capture, household notes, decision logs |

### Tier 2b: Plane Project Management Stack

Plane provides cross-persona task delegation, case management, and governance tracking — exposed through `plane-mcp` (59 tools). The stack runs as 12 containers with a dedicated Valkey instance.

| Service | Image | Depends On | Description |
|---------|-------|------------|-------------|
| `plane-api` | Plane (latest) | PostgreSQL, plane-valkey, plane-mq | Core API server |
| `plane-worker` | Plane (latest) | PostgreSQL, plane-valkey, plane-mq | Background job processing |
| `plane-beat` | Plane (latest) | PostgreSQL, plane-valkey, plane-mq | Periodic task scheduler |
| `plane-web` | Plane (latest) | plane-api | Web frontend |
| `plane-admin` | Plane (latest) | plane-api | Admin panel |
| `plane-space` | Plane (latest) | plane-api | Public project spaces |
| `plane-live` | Plane (latest) | plane-api | Real-time collaboration |
| `plane-proxy` | Plane (latest) | plane-web, plane-api | Reverse proxy |
| `plane-migrator` | Plane (latest) | PostgreSQL | Database migration runner |
| `plane-valkey` | Valkey 8 | — | Dedicated cache/queue (Redis-compatible) |
| `plane-mq` | Valkey 8 | — | Dedicated message queue |
| `plane-minio` | Minio (latest) | — | S3-compatible object storage for attachments |

> **Note on Plane workspaces**: StewardOS configures 7 domain-scoped workspaces (chief-of-staff, estate-counsel, household-finance, household-ops, investment-office, wellness, insurance). Each persona's `PLANE_HOME_WORKSPACE` determines write access boundaries.

### Tier 3: Support Services

Infrastructure utilities that are not systems of record.

| Service | Image | Description |
|---------|-------|-------------|
| `vaultwarden` | Vaultwarden 1.35 | Credential vault |
| `watchtower` | Watchtower (latest) | Optional rolling container image update automation |

### Contracted files in this repository

- [`services/docker-compose.yml`](../../../services/docker-compose.yml)
- [`services/.env.example`](../../../services/.env.example)
- [`services/personal-db/init-stewardos-db.sh`](../../../services/personal-db/init-stewardos-db.sh)
- [`services/personal-db/core_schema.sql`](../../../services/personal-db/core_schema.sql)
- [`services/personal-db/finance_schema.sql`](../../../services/personal-db/finance_schema.sql)
- [`services/personal-db/estate_schema.sql`](../../../services/personal-db/estate_schema.sql)
- [`services/personal-db/health_schema.sql`](../../../services/personal-db/health_schema.sql)
- [`services/wger/nginx.conf`](../../../services/wger/nginx.conf)
- [`services/plane/`](../../../services/plane/) — Plane stack configuration and workspace taxonomy
- [`services/cloudflared/config.yml.template`](../../../services/cloudflared/config.yml.template)

## Workflows

See [README.md](../../../README.md#what-this-system-actually-does) for end-to-end workflow examples showing how self-hosted services participate in persona workflows through MCP servers.

## Customization and extension

### Safe customization pattern

1. Add/update service blocks in [`services/docker-compose.yml`](../../../services/docker-compose.yml).
2. Add any new variables to [`services/.env.example`](../../../services/.env.example) with placeholder values only.
3. Prefer loopback binds (`127.0.0.1:host:container`) and explicit healthchecks.
4. Update corresponding MCP/persona docs so behavior stays discoverable.

### Common extensions

- Swap storage backends or tune resource envelopes for smaller/larger hosts.
- Add reverse proxy or edge ingress while keeping internal services private.
- Add domain-specific OSS apps (for example CRM, billing, or observability) and expose them via new MCP servers.

## Boundaries

- This layer owns application/runtime state and persistence.
- It does not define agent policy, persona authority, or tool safety rules.
- Persona contracts live in `agent-configs/*/AGENTS.md`; runtime daemons live in `agents/`.
