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
| `personal-db` | PostgreSQL 16 | Paperless-ngx, Ghostfolio, wger, Directus, n8n, estate-planning-mcp, finance-graph-mcp, household-tax-mcp | Shared relational database for all stateful services |
| `personal-redis` | Redis 7 | Paperless-ngx, Ghostfolio, wger | Cache/queue backend |

### Tier 2: Application Services

Domain-specific applications that serve as systems of record, each exposed to personas through MCP servers.

| Service | Image | Depends On | MCP Server | Description |
|---------|-------|------------|------------|-------------|
| `paperless-ngx` | Paperless-ngx 2.20 | PostgreSQL, Redis | `paperless-mcp`, `health-records-mcp` | Document ingestion, OCR, tagging, retrieval |
| `ghostfolio` | Ghostfolio 2.243 | PostgreSQL, Redis | `ghostfolio-mcp`, `portfolio-analytics` | Portfolio tracking and holdings context |
| `actual-budget` | Actual Server 26.2 | — | `actual-mcp` | Household budgeting and transaction ledger |
| `mealie` | Mealie v3.11 | — | `mealie-mcp-server` | Recipes and weekly meal planning |
| `grocy` | Grocy 4.5 | — | `grocy-mcp` | Pantry and consumable inventory |
| `wger-web` + celery + nginx | wger 2.3-dev | PostgreSQL, Redis | `wger-mcp` | Fitness and nutrition tracking |
| `homebox` | Homebox 0.23 | — | `homebox-mcp` | Household asset/inventory tracking |
| `memos` | Memos 0.26 | — | `memos-mcp` | Quick capture, household notes, decision logs |
| `directus` | Directus (latest) | PostgreSQL | — | Visual editor for estate-planning PostgreSQL schema |

> **Note on Directus**: Directus provides a UI/API surface over the `estate_planning` database schema for visual editing and review. It is not required for MCP tool access — `estate-planning-mcp` connects to PostgreSQL directly. Directus is a convenience layer for human operators.

### Tier 3: Support Services

Infrastructure utilities that are not systems of record.

| Service | Image | Description |
|---------|-------|-------------|
| `vaultwarden` | Vaultwarden 1.35 | Credential vault |
| `changedetection` | changedetection.io 0.54 | Website and page change monitoring |
| `n8n` | n8n (latest) | Automation workflows between services (depends on PostgreSQL) |
| `watchtower` | Watchtower (latest) | Optional rolling container image update automation |

### Contracted files in this repository

- [`services/docker-compose.yml`](../../../services/docker-compose.yml)
- [`services/.env.example`](../../../services/.env.example)
- [`services/personal-db/init-databases.sh`](../../../services/personal-db/init-databases.sh)
- [`services/wger/nginx.conf`](../../../services/wger/nginx.conf)
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
