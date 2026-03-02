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

### Core infrastructure

- `personal-db` (PostgreSQL 16): shared data plane for Paperless, Ghostfolio, wger, Directus, n8n, and graph services.
- `personal-redis` (Redis 7): cache/queue backend for Paperless, Ghostfolio, wger.

### Application services

- `vaultwarden`: credential vault.
- `paperless-ngx`: document ingestion, OCR, tagging, retrieval.
- `ghostfolio`: portfolio tracking and holdings context.
- `mealie`: recipes and weekly meal planning.
- `actual-budget`: household budgeting and transaction ledger.
- `memos`: quick capture, household notes, lightweight decision logs.
- `homebox`: household asset/inventory tracking.
- `changedetection`: website and page change monitoring.
- `grocy`: pantry and consumable inventory.
- `wger-web` + celery + nginx: fitness and nutrition tracking.
- `directus`: UI/API surface over estate graph schema.
- `n8n`: automation workflows between services.
- `watchtower`: optional rolling container image update automation.

### Contracted files in this repository

- [`services/docker-compose.yml`](../../../services/docker-compose.yml)
- [`services/.env.example`](../../../services/.env.example)
- [`services/personal-db/init-databases.sh`](../../../services/personal-db/init-databases.sh)
- [`services/wger/nginx.conf`](../../../services/wger/nginx.conf)
- [`services/cloudflared/config.yml.template`](../../../services/cloudflared/config.yml.template)

## How this layer participates in workflows

### 1. Monthly household close (Comptroller)

1. `actual-budget` provides transaction/cashflow truth.
2. `ghostfolio` provides portfolio and dividend context.
3. `personal-db` persists consolidated statement facts through finance MCP tools.
4. Persona output becomes a reconciled monthly summary with provenance.

### 2. Estate documentation lifecycle (Estate Counsel)

1. Legal/estate docs are ingested in `paperless-ngx`.
2. Estate graph metadata is updated through MCP servers backed by `personal-db`.
3. `directus` exposes editable/visual review of entity and ownership records.

### 3. Household operations planning (Director + Wellness)

1. `mealie` provides meal plans and shopping context.
2. `grocy` and `homebox` provide pantry/inventory constraints.
3. `wger` + health MCP flows provide fitness and wellness continuity.

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
