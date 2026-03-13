# StewardOS Roadmap

This roadmap tracks the evolution of StewardOS from a local-first integration workspace into a fully self-hosted family-office operating system.

## Phase 1: Data Population and Operational Baselines (Complete)

### Estate graph population

- complete person/entity/asset records,
- link key documents to entities and assets,
- validate recursive ownership paths with real multi-level structures,
- establish critical date coverage (filings, renewals, distributions).

### Workflow automation baseline

- document ingestion to estate graph,
- portfolio valuation sync into finance graph,
- budget cash-position sync into finance graph,
- critical-date calendar sync.

## Phase 2: Estate and Financial Service Expansion (Complete)

### Estate schema evolution

- obligations and liability linkage,
- account signer/beneficiary tracking,
- family relationship modeling,
- role assignment by entity/jurisdiction.

### Estate MCP expansion

- ownership visualization export tooling,
- richer cross-entity search and filters,
- compliance and review-cycle tooling.

### Household tax engine

- TY2025 US federal + MA state conformity,
- itemized deductions, AMT, child tax credit,
- golden-file test fixtures for deterministic verification.

### Health graph (assertion-first)

- replaced `health-records-mcp` with `health-graph-mcp`,
- genomics, clinical assertions, labs, coverage intelligence,
- characterization tests + DI tests.

## Phase 3: Control Plane and Governance (Complete)

### Plane project management integration

- 58 governance-safe PM tools across 12 modules in `plane-mcp`,
- 7 domain-scoped workspaces with standard label taxonomy,
- all write tools validate `PLANE_HOME_WORKSPACE` for governance enforcement,
- 126 tests with `MockPlaneClient`.

### Persona expansion

- 8 personas (added Insurance Advisor, Research Analyst; renamed Investment Officer to Portfolio Manager),
- Gmail plus-addressing for per-persona email identity (filters, labels, send-as),
- skill reorganization: 5 IO skills migrated to Research Analyst.

### Mail worker hardening

- ActionAck model (unified reply/delegate/maintenance),
- Plane poller for case completion detection,
- Plane webhook ingress with HMAC-SHA256 verification,
- PM session tables and delivery-ID idempotency.

### Infrastructure consolidation

- added Plane stack (12 containers + dedicated Valkey),
- dropped n8n, Directus, changedetection.io,
- shared agent library (`agents/lib/`) for gmail_watch, pubsub_validation, schedule_loader.

## Phase 4: Runtime Consolidation on Server Infrastructure

### Agent runtime migration

- move agent config execution from workstation to server runtime,
- co-locate persona configs and MCP runtimes with core services,
- standardize host-level service templates and deployment scripts.

### Remove intermediary ingress dependency

- retire `agent-mail.<domain>` as a required relay hop,
- run ingress and worker in a direct server-side path,
- tighten trust boundaries to internal service network + auth headers.

### Remove SSH tunnel MCP dependency

- run MCP servers adjacent to service data plane,
- replace tunnel-based local development bridges with local server sockets,
- update persona config examples to server-local endpoints.

## Phase 5: Release Engineering and Community Readiness

- complete sanitized public examples for all sensitive runtime files,
- pin upstream/fork dependencies with reproducible bootstrap tooling,
- document contribution and security workflows,
- publish stable versioned release notes.

## Ongoing Streams

- security hardening and secret rotation,
- backup durability and restore testing,
- OAuth scope minimization,
- observability and incident runbooks.

### Wellness Data Automation

- automate Apple Health ingestion into the MCP data plane (remove manual zip/csv operator flow),
- evaluate and productionize push/sync ingestion (open-wearables pilot + fallback cron-based import path),
- keep direct high-granularity connectors (Peloton API + FitBod CSV/wger pipeline) as primary sources for coaching analytics,
- enforce freshness checks for Apple Health, Peloton, and wger before weekly wellness email synthesis.
