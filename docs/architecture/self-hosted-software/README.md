# Self-Hosted Software

StewardOS uses Docker Compose as the baseline platform runtime for the household/family-office application stack.

## Why this layer matters

This layer provides the source systems and operational surfaces that personas and MCP servers depend on. Without this layer, agents become disconnected from real state.

## OSS stack components

The current stack includes:

- PostgreSQL and Redis infrastructure
- Vaultwarden (password management)
- Paperless-ngx (document management)
- Ghostfolio (portfolio tracking)
- Mealie (meal planning)
- Actual Budget (cash-flow and budgeting)
- Memos (notes/decision capture)
- Homebox (household inventory)
- changedetection.io (monitoring/alerts)
- Grocy (pantry/inventory)
- wger (fitness tracking)
- Directus (estate graph UI/API layer)
- n8n (workflow automation)

## Runtime characteristics

- loopback-bound ports by default,
- explicit healthchecks for critical services,
- resource controls for constrained hosts,
- env-driven URL/domain and secret configuration.

## Public compose contract

Tracked files:

- `services/docker-compose.yml`
- `services/.env.example`
- `services/personal-db/init-databases.sh`
- service-specific support configs under `services/`

## Example operational scenarios

- Bring up the full data platform for persona workflows.
- Use n8n + MCP servers for periodic synchronization tasks.
- Run estate and finance data stores with isolated schema ownership.

## Boundary

This layer provides applications and storage only. Agent execution policy and persona constraints are defined in `agent-configs/` and `agents/`.
