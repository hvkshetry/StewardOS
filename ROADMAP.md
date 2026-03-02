# StewardOS Roadmap

This roadmap tracks the evolution of StewardOS from a local-first integration workspace into a fully self-hosted family-office operating system.

## Phase 1: Data Population and Operational Baselines

### Estate graph population

- complete person/entity/asset records,
- link key documents to entities and assets,
- validate recursive ownership paths with real multi-level structures,
- establish critical date coverage (filings, renewals, distributions).

### Workflow automation baseline

- document ingestion to estate graph,
- portfolio valuation sync into finance graph,
- budget cash-position sync into finance graph,
- critical-date calendar sync,
- change-detection to memo capture.

## Phase 2: Estate Service Expansion

### Estate schema evolution

- obligations and liability linkage,
- account signer/beneficiary tracking,
- family relationship modeling,
- role assignment by entity/jurisdiction.

### Estate MCP expansion

- ownership visualization export tooling,
- richer cross-entity search and filters,
- compliance and review-cycle tooling.

### UI and stewardship tooling

- interactive ownership graph views,
- entity-centric dashboards,
- operational compliance queues.

## Phase 3: Financial Control Plane Hardening

- monthly close reliability and statement fact quality,
- audit logging and immutable event trails,
- stricter write-path governance across personas,
- deterministic reconciliation workflows.

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
