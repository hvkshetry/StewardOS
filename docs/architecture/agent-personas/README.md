# Agent Personas

StewardOS uses role-specific personas with explicit boundaries. Each persona operates within a dedicated Plane workspace and communicates via a unique Gmail plus-address identity.

## Persona Model

Each persona defines:

- mission and responsibility scope,
- approved MCP server access (least-privilege),
- Plane home workspace for task management,
- Gmail plus-address for inbound/outbound correspondence,
- operational constraints and escalation behavior.

## Current Persona Set (8 Personas)

| Persona | Plane Workspace | Email Alias | Primary Domain |
|---------|----------------|-------------|----------------|
| Chief of Staff | `chief-of-staff` | `+cos` | Operations, administration, document triage, cross-persona orchestration |
| Estate Counsel | `estate-counsel` | `+estate` | Legal entities, succession, compliance (US + India jurisdictions) |
| Household Comptroller | `household-finance` | `+hc` | Cash, budget, exact TY2025 US+MA tax engine, financial statements |
| Household Director | `household-ops` | `+hd` | Meals, grocery, pantry, child education/development |
| Portfolio Manager | `investment-office` | `+io` | Portfolio risk, rebalancing, illiquid assets, tax-loss harvesting |
| Research Analyst | `investment-office` | `+ra` | Market research, DCF/comps models, SEC filings, sector analysis |
| Insurance Advisor | `insurance` | `+insurance` | Policies, claims, coverage adequacy, renewal tracking |
| Wellness Advisor | `wellness` | `+wellness` | Genome-aware health, fitness, nutrition, sleep/recovery, medical records |

Portfolio Manager and Research Analyst share the `investment-office` workspace with distinct write scopes. See [Plane Workspaces](../../../services/plane/WORKSPACES.md) for the full domain taxonomy.

## Boundary Design Principles

- least-privilege MCP access — each persona sees only tools relevant to its domain,
- clear ownership of write paths — no two personas write to the same data domain,
- auditable routing for automated correspondence via persona-specific plus-addresses,
- strict separation between personal read-only context and agent write channels,
- cross-domain delegation flows through Plane work items, not direct inter-agent calls.

## Gmail Plus-Addressing

Each persona sends and receives email via a `+alias` suffix on a shared agent inbox. See [Gmail Plus-Addressing](../gmail-plus-addressing/README.md) for the full architecture: filters, labels, send-as identities, and MCP tool call mechanics.

## Persona Configuration

Persona configs live in `agent-configs/<persona>/AGENTS.md` and include:

- complete tool inventory with read/write annotations,
- available slash commands and skills,
- MCP server wiring and environment variables,
- Plane workspace assignment via `PLANE_HOME_WORKSPACE`.
