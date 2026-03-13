# Release Notes — 2026-03-13

Major sync bringing Plane control plane, persona expansion, tax engine TY2025, and infrastructure consolidation to the public repo.

## Plane Project Management Integration (New)

- Added `servers/plane-mcp/` — 58 governance-safe PM tools across 12 modules (discovery, creation, execution, projects, cycles, modules, pages, coordination, management, views, estimates, relations)
- 126 tests with `MockPlaneClient` using `__getattr__` for dynamic SDK method mocking
- All write tools validate `PLANE_HOME_WORKSPACE` for governance enforcement
- Added `services/plane/` — full Plane Docker stack (12 containers + dedicated Valkey)
- Added `services/plane/WORKSPACES.md` — 7 domain-scoped workspace taxonomy

## Persona Expansion (6 → 8)

- **Insurance Advisor** (`+insurance`, workspace: `insurance`) — policies, claims, coverage review
- **Research Analyst** (`+ra`, workspace: `investment-office`) — market briefing, DCF models, sector analysis
- Renamed Investment Officer → **Portfolio Manager** (alias `+io` unchanged)
- 5 investment skills migrated from Portfolio Manager to Research Analyst (comps-analysis, dcf-model, market-briefing, returns-analysis, unit-economics)

## Household Tax TY2025

- Added `servers/household-tax-mcp/` — exact-scope US federal + MA state conformity engine
- Itemized deductions, AMT, child tax credit, golden-file test fixtures

## Mail Worker Hardening

- `ActionAck` model for unified reply/delegate/maintenance actions
- Plane poller for case completion and delegation event detection
- Plane webhook handler with HMAC-SHA256 verification (forwarded via ingress)
- PM session tables and delivery-ID idempotency
- Shared agent library extracted to `agents/lib/` (gmail_watch, pubsub_validation, schedule_loader)

## Infrastructure Changes

- **Added:** Full Plane stack, dedicated Valkey, Plane webhook ingress endpoint
- **Removed:** n8n (workflow automation), Directus (data studio), changedetection.io (web monitoring)
- All replaced by Plane-based task management and agent-driven automation

## Documentation

- New: [Gmail Plus-Addressing Architecture](docs/architecture/gmail-plus-addressing/README.md)
- Updated: all 6 architecture docs for 8-persona model, Plane, and infrastructure changes
- Updated: README, ROADMAP, CONTRIBUTING for current state
- Updated: AI Agent Architecture Primer (Plane port mappings, source-of-truth table)
- Added: completed plan docs for plane-control-plane and household-tax-ty2025

## Testing

- 411 tests across 19 projects (126 plane-mcp, 25 mail-worker)
- CI matrix updated for new servers and agents
- Skill-to-tool contract verification in CI
