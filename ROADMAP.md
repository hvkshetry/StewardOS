# StewardOS Roadmap

## Completed

- Full estate entity/asset/person graph with recursive ownership chains, jurisdiction tracking, and beneficial interest semantics
- Portfolio risk engine v2: Student-t ES, illiquid overlay, FX risk, vol regime detection, concentration analysis
- Risk engine v2.1: regime-conditional stress testing, valuation staleness detection with vol uplift, tax-aware de-risking
- Household-tax v2 → v3: exact 2025/2026 US+MA individual and fiduciary returns with CTC, AMT, itemized deductions, safe-harbor planning, and golden-file-verified accuracy
- Finance graph liability tracking: mortgage/HELOC/ARM rate management, amortization schedules, refinance NPV analysis
- Family-edu PostgreSQL control plane: learner records, milestone tracking, evidence pipeline, activity planning
- Email-driven autonomous agent runtime: Gmail Pub/Sub → webhook → persona-routed worker → agent execution
- Scheduled briefing agent with daily/weekly cadence
- Plane PM integration (Phase 0-2): 59 governance-safe tools across 12 modules, 7 domain-scoped workspaces, webhook + poller event strategy, cross-persona task delegation
- Persona expansion to 8 roles: added Insurance Advisor, Research Analyst; renamed Investment Officer → Portfolio Manager with PM/RA research delegation split
- Health-graph-mcp: genome-aware health database replacing health-records-mcp — 23andMe genotype ingestion, clinical variant assertions, pharmacogenomics, polygenic risk scores (27 tools, 10 modules)
- 57 persona skills across 8 roles (Portfolio Manager, Research Analyst, Household Comptroller, Estate Counsel, Household Director, Wellness Advisor, Insurance Advisor, Chief of Staff)
- Mail worker hardening: ActionAck model (unified reply/delegate/maintenance), PM session tables, Plane polling loop, delegation via Plane as single source of truth
- Infrastructure: dropped n8n/Directus/changedetection; added 12-container Plane stack with dedicated Valkey
- Shared agent lib (`agents/lib/`): pubsub validation, Gmail watch, schedule loader
- Shared domain lib (`servers/lib/stewardos_lib/`): db, constants, json_utils, domain_ops
- CI pipeline (`.github/workflows/ci.yml`) and root Makefile test orchestration (411 tests across 19 projects)
- News provider migration: GDELT → Google News RSS + yfinance for market news
- OCF (Open Cap Format) ingestion for private company cap table tracking
- Document lifecycle: Paperless-ngx integration with estate entity linking, review policies, version chain tracking

## In Progress

- **Runtime consolidation**: migrate agent execution from workstation to server infrastructure — co-locate persona configs and MCP runtimes with core services
- **Direct ingress**: remove intermediary email relay dependency — run ingress and worker in a direct server-side path
- **MCP locality**: co-locate MCP servers with service data plane — replace tunnel-based development bridges with local server sockets

## Next

- Index fund look-through for concentration risk: decompose ETF holdings into underlying positions for accurate exposure analysis
- Interactive ownership graph visualization via Plane pages or dedicated UI
- Deterministic reconciliation workflows with audit trails
- Community contribution infrastructure: skill testing harness, CI for skill PRs, contributor onboarding automation

## Ongoing

- Security hardening and secret rotation
- Backup durability and restore testing
- OAuth scope minimization
- Observability and incident runbooks
