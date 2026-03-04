# StewardOS

StewardOS is a self-hosted family-office operating system. It combines 14 open-source applications, 20 MCP servers, 6 role-scoped agent personas, and 50 reusable skills into one platform that runs household finance, investment management, estate planning, health tracking, and daily operations — with an autonomous agent runtime that executes workflows on schedule or in response to incoming email.

> **If you manage your own portfolio, run your own household budget, track your own health, or handle your own estate planning** — StewardOS encodes workflows you already do manually so they run consistently every time. Jump to the [persona](#the-persona-model) that matches how you manage your own affairs.

## What This System Actually Does

### Portfolio & Risk Management

- **Fat-tail risk modeling**: Expected Shortfall (worst-case portfolio loss estimate) computed with Student-t distributions instead of normal distributions — captures the extreme moves that matter most
- **Illiquid asset overlay**: Private equity, real estate, and other illiquid holdings integrated into risk calculations with regime-conditional stress testing (2008, COVID, rate shock scenarios)
- **Valuation staleness detection**: Identifies stale price data on illiquid positions and applies volatility uplift so risk isn't understated
- **Tax-loss harvesting integrated with risk constraints**: Harvest losses only when the resulting portfolio still meets ES limits — no blind selling
- **SEC filing analysis**: 10-K/10-Q financials, 8-K event detection, insider transaction tracking, and 13F institutional ownership via EDGAR
- **Market intelligence**: Real-time indices, FRED macro indicators, CFTC Commitment of Traders positioning, options chains, and news scanning
- **16 investment skills** covering morning briefings, portfolio review, rebalancing, DCF modeling, comparable analysis, due diligence, and client reporting

### Household Finance

- **Automated monthly close**: Reconcile Actual Budget transactions with Ghostfolio portfolio data and finance graph context, then persist P&L / balance sheet / cash flow statements with line-item provenance
- **12-scenario tax optimization**: Evaluate strategies across Roth conversion, capital gain timing, charitable giving, and estimated payments with multi-year simulation and PostgreSQL persistence
- **Liability tracking and refinance analysis**: Mortgage/HELOC/ARM rate tracking, amortization schedules, and NPV-based refinance economics
- **Cash flow forecasting and net worth roll-up**: Aggregate across entities, account types, and asset classes with liability-adjusted totals

### Estate & Compliance

- **Entity/asset/person graph**: Trusts, LLCs, corporations, and HUFs with recursive ownership chains, jurisdiction tracking, and beneficial interest semantics
- **Document lifecycle**: Ingest via Paperless-ngx, classify, link to estate entities, set review policies, track document supersession, and attach compliance evidence
- **Succession planning**: Beneficiary designations, fiduciary role assignments, family relationship modeling, and critical date calendaring
- **Compliance tracking**: Obligation definitions with instance lifecycle, evidence linking, and filing status monitoring

### Household Operations

- **Meal planning and grocery management**: Mealie recipes feed into weekly meal plans, Grocy tracks pantry inventory, and shopping lists auto-populate from stock shortfalls and expiring items
- **Child development tracking**: Learner profiles with milestone tracking, evidence pipeline (link Paperless documents to assessments), activity planning by age, and term brief generation
- **Home inventory**: Homebox tracks household assets with location hierarchy, maintenance logs, and asset tagging
- **Weekly planning**: Integrates meals, activities, calendar, and health context into one operational plan

### Health & Wellness

- **Workout and nutrition tracking**: wger logs exercises, body weight, and nutrition diary entries with macro calculations
- **Medical records management**: Health documents organized in Paperless-ngx with provider tracking, prescription lists, lab results, and insurance documents
- **Sleep and activity data**: Oura ring and Apple Health integrations feed recovery and readiness context
- **Weekly health synthesis**: Correlate sleep quality, workout load, nutrition adherence, and body composition trends

### Autonomous Agent Runtime

- **Gmail Pub/Sub webhook pipeline**: Incoming email triggers persona-routed agent execution — forward a document and it gets auto-filed and linked to the right estate entity
- **Scheduled briefings**: Daily market scans, weekly household reviews, and periodic compliance checks run without manual intervention
- **Persona-scoped execution**: Each agent runs within its declared tool boundaries — the Investment Officer cannot modify budget data, the Comptroller cannot execute trades

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────┐
│  User / Email / Schedule                                │
│    ↓                                                    │
│  Agent Runtime (systemd services)                       │
│    ↓                                                    │
│  Persona Layer (6 roles × skills)                       │
│    ↓                                                    │
│  MCP Server Layer (13 first-party + 7 upstream)         │
│    ↓                                                    │
│  Self-Hosted Application Stack (14 services via Compose)│
│    ↓                                                    │
│  PostgreSQL · Redis · Filesystem                        │
└─────────────────────────────────────────────────────────┘
```

| Layer | Count | Examples |
|-------|-------|---------|
| Self-hosted apps | 14 | Ghostfolio, Actual Budget, Paperless-ngx, Mealie, Grocy, wger, Homebox, Directus, Memos |
| MCP servers | 20 | `portfolio-analytics`, `market-intel-direct`, `estate-planning-mcp`, `household-tax-mcp`, `health-records-mcp` |
| Agent personas | 6 | Investment Officer, Household Comptroller, Estate Counsel, Household Director, Wellness Advisor, Chief of Staff |
| Persona skills | 50 | `/portfolio-review`, `/monthly-close`, `/plan-week`, `/morning-check`, `/weekly-review`, `/estate-overview` |

Detailed architecture docs: [Self-Hosted Software](docs/architecture/self-hosted-software/README.md) · [MCP Servers](docs/architecture/mcp-servers/README.md) · [Agent Personas](docs/architecture/agent-personas/README.md) · [Agent Skills](docs/architecture/agent-skills/README.md) · [systemd Runtime](docs/architecture/systemd-runtime/README.md)

## The Persona Model

Each persona has an explicit contract defining which MCP servers it can access, what it can read vs write, and when it must escalate to another persona.

| Persona | Skills | Key MCP Servers | Example Workflow |
|---------|--------|-----------------|------------------|
| **Investment Officer** | 16 | portfolio-analytics, market-intel-direct, policy-events, ghostfolio, household-tax, sec-edgar | `/portfolio-review` chains 10+ tool calls across risk analysis (Student-t ES, illiquid overlay), allocation drift, TLH scan, tax overlay, and market context |
| **Household Comptroller** | 6 | household-tax, finance-graph, actual, ghostfolio | `/monthly-close` reconciles Actual Budget + Ghostfolio + finance graph, persists P&L/BS/CFS line items, and flags anomalies |
| **Estate Counsel** | 7 | estate-planning, finance-graph, paperless | `/estate-overview` traverses the entity graph with recursive ownership chains, net worth by jurisdiction, and upcoming critical dates |
| **Household Director** | 7 | mealie, grocy, family-edu, homebox | `/plan-week` integrates meal plans, pantry inventory, child activities, and calendar into one weekly operational plan |
| **Wellness Advisor** | 6 | health-records, wger, oura, apple-health | `/morning-check` synthesizes overnight sleep data, readiness scores, and workout schedule into recovery recommendations |
| **Chief of Staff** | 8 | paperless, memos, google-workspace | `/weekly-review` aggregates tasks, expiring documents, budget status, and cross-persona outputs into an executive brief |

Full persona contracts: [`agent-configs/*/AGENTS.md`](agent-configs/)

## Quick Start

1. Copy service env template:
   ```bash
   cp services/.env.example services/.env
   ```
2. Fill required values in `services/.env`.
3. Start platform stack:
   ```bash
   docker compose -f services/docker-compose.yml up -d
   ```
4. Bootstrap upstream MCP dependencies:
   ```bash
   scripts/bootstrap_upstreams.sh
   ```
5. Verify pinned MCP checkouts:
   ```bash
   scripts/verify_upstreams.sh
   ```
6. Link persona runtime skills from tracked sources:
   ```bash
   scripts/bootstrap_persona_skills.sh
   ```

## Contributing

StewardOS is built for people who manage their own affairs and have developed real expertise doing it.

If you run your own portfolio, manage your household budget, track your own health, or handle your family's estate planning — you already have workflows that work. Contributing a skill means encoding what you've learned so it runs consistently every time, and sharing it with others who manage their own affairs the same way.

### What makes a good skill contribution

- A workflow you actually use to manage your own finances, health, household, or estate
- Uses existing MCP tools — skills are markdown files, no server changes needed
- Encodes practical judgment from real experience, not generic advice

### Where to start

1. Pick the persona that matches how you manage your own affairs
2. Read 2-3 existing skills in that persona to understand the pattern (`skills/personas/<persona>/`)
3. Identify a workflow gap or quality improvement from your own experience
4. See the [Skill Contribution Guide](docs/community/skill-contribution-guide.md) and [CONTRIBUTING.md](CONTRIBUTING.md)

## Agent Runtime Compatibility

StewardOS can be integrated with any agent runtime that supports MCP server tool invocation, skill-aware prompting, and deterministic non-interactive execution in service contexts.

## Repository Layout

- `services/` — Docker Compose platform stack and operational scripts
- `servers/` — First-party MCP servers plus pinned upstream checkout paths
- `agent-configs/` — Persona contracts (`AGENTS.md`) and runtime configs
- `agents/` — Webhook ingress, mail worker, and scheduled briefing services
- `skills/` — Reusable skills organized by persona (`skills/personas/<persona>/`)
- `docs/` — Architecture, provisioning, and governance documentation

## Security and Sanitization

- Live secrets and runtime state are excluded from tracked public files
- Public configs are provided as sanitized templates (`.example` files)
- See [SECURITY.md](SECURITY.md) and [Release Checklist](docs/RELEASE_CHECKLIST.md)

## Roadmap

See [ROADMAP.md](ROADMAP.md).
