# StewardOS Roadmap

## Completed

- Full estate entity/asset/person graph with recursive ownership chains, jurisdiction tracking, and beneficial interest semantics
- Portfolio risk engine v2: Student-t ES, illiquid overlay, FX risk, vol regime detection, concentration analysis
- Risk engine v2.1: regime-conditional stress testing, valuation staleness detection with vol uplift, tax-aware de-risking
- Household-tax v2 with 12-scenario evaluator, multi-year simulation, and PostgreSQL persistence
- Finance graph liability tracking: mortgage/HELOC/ARM rate management, amortization schedules, refinance NPV analysis
- Family-edu PostgreSQL control plane: learner records, milestone tracking, evidence pipeline, activity planning
- Email-driven autonomous agent runtime: Gmail Pub/Sub → webhook → persona-routed worker → agent execution
- Scheduled briefing agent with daily/weekly cadence
- 50 persona skills across 6 roles (Investment Officer, Household Comptroller, Estate Counsel, Household Director, Wellness Advisor, Chief of Staff)
- News provider migration: GDELT → Google News RSS + yfinance for market news
- OCF (Open Cap Format) ingestion for private company cap table tracking
- Document lifecycle: Paperless-ngx integration with estate entity linking, review policies, version chain tracking

## In Progress

- **Runtime consolidation**: migrate agent execution from workstation to server infrastructure — co-locate persona configs and MCP runtimes with core services
- **Direct ingress**: remove intermediary email relay dependency — run ingress and worker in a direct server-side path
- **MCP locality**: co-locate MCP servers with service data plane — replace tunnel-based development bridges with local server sockets

## Next

- Index fund look-through for concentration risk: decompose ETF holdings into underlying positions for accurate exposure analysis
- Interactive ownership graph visualization via Directus
- Deterministic reconciliation workflows with audit trails
- Community contribution infrastructure: skill testing harness, CI for skill PRs, contributor onboarding automation

## Ongoing

- Security hardening and secret rotation
- Backup durability and restore testing
- OAuth scope minimization
- Observability and incident runbooks
