# StewardOS

StewardOS is a self-hosted family-office operating system that combines a curated OSS application stack, MCP servers, role-based agent personas, and reusable skills into one auditable workflow platform.

## Why StewardOS Exists

Most home-lab and agent repositories solve isolated problems. StewardOS is designed for real household and family-office operations where tasks span multiple systems:

- financial tracking,
- document lifecycle and compliance,
- calendaring and communication,
- household logistics,
- estate and planning workflows.

The core principle is **structured delegation**: each persona has explicit scope, tools, and boundaries.

## Core Capabilities

### 1. Unified self-hosted control plane
StewardOS runs a full local stack of production-grade OSS software:

- PostgreSQL
- Redis
- Vaultwarden
- Paperless-ngx
- Ghostfolio
- Mealie
- Actual Budget
- Memos
- Homebox
- changedetection.io
- Grocy
- wger
- Directus
- n8n
- Cloudflared (optional host ingress)

### 2. MCP-driven data/action layer
StewardOS combines first-party MCP servers with pinned upstream/forked servers to expose tools for estate graphing, portfolio analytics, policy-event tracking, household tax logic, health/fitness workflows, and document automation.

### 3. Persona-based operating model
Personas include:

- Chief of Staff
- Estate Counsel
- Household Comptroller
- Household Director
- Investment Officer
- Wellness Advisor

Each persona has role-specific MCP access and communication policy.

### 4. Skill library and repeatable playbooks
Skills capture recurring workflows so the system can run consistently over time instead of relying on ad-hoc prompts.

StewardOS uses a layered skill ecosystem:

- repository-tracked portable skills under `skills/`,
- persona-local runtime skill overlays under `agent-configs/*/.codex/skills/`,
- optional symlinked shared/global packs (environment-managed).

## Example Workflows

- **Comptroller monthly close**: reconcile Actual + Ghostfolio + finance graph data, flag anomalies, and produce action-ready summaries.
- **Wellness coordination**: combine meal planning, activity tracking, and records workflows into weekly recommendations.
- **Investment monitoring**: run market/policy context checks, risk views, and tax-aware prompts under explicit governance.
- **Document stewardship**: ingest, classify, and retrieve household/estate documents with proper metadata.

## Architecture

- Self-hosted software stack: [Self-Hosted Software](docs/architecture/self-hosted-software/README.md)
- MCP server layer: [MCP Servers](docs/architecture/mcp-servers/README.md)
- Agent skill system: [Agent Skills](docs/architecture/agent-skills/README.md)
- Persona boundaries: [Agent Personas](docs/architecture/agent-personas/README.md)
- Runtime topology: [systemd Runtime](docs/architecture/systemd-runtime/README.md)
- Provisioning templates: [Provisioning Guide](docs/provisioning/README.md)

## Repository Layout

- `services/`: Docker Compose platform stack and operational scripts.
- `servers/`: first-party MCP servers plus pinned upstream checkout paths.
- `agent-configs/`: persona MCP/runtime configs (sanitized examples).
- `agents/`: webhook ingress + worker/brief runtime services.
- `skills/`: reusable skills (`core`, `shared`, and `personas/<persona>/` packs).
- `docs/`: architecture, provisioning, and governance docs.

## Quick Start (Current)

1. Copy service env template:
   - `cp services/.env.example services/.env`
2. Fill required values in `services/.env`.
3. Start platform stack:
   - `docker compose -f services/docker-compose.yml up -d`
4. Bootstrap upstream MCP dependencies:
   - `scripts/bootstrap_upstreams.sh`
5. Verify pinned MCP checkouts:
   - `scripts/verify_upstreams.sh`
6. Link persona runtime skills from tracked `skills/` sources:
   - `scripts/bootstrap_persona_skills.sh`

## Agent Runtime Compatibility

StewardOS can be integrated with any agent runtime that supports:

- MCP server tool invocation,
- skill-aware prompting/workflow composition,
- deterministic non-interactive execution in service contexts.

The current reference implementation and examples use Codex CLI, but the architecture is runtime-agnostic by design.

## Community Contribution Priorities

StewardOS is explicitly built for domain experts to contribute practical skills:

- nutrition/fitness experts for Wellness Advisor,
- investors/analysts for Investment Officer,
- CPAs/bookkeepers for Household Comptroller,
- estate/legal practitioners for Estate Counsel,
- household operations specialists for Director/COS flows.

Contribution entry point:
- [Skill Contribution Guide](docs/community/skill-contribution-guide.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

## Security and Sanitization

- Live secrets/runtime state are excluded from tracked public files.
- Public configs are provided as sanitized templates.
- See [SECURITY.md](SECURITY.md) and [Release Checklist](docs/RELEASE_CHECKLIST.md).

## Roadmap

See [ROADMAP.md](ROADMAP.md).
