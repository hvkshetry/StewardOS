# Agent Personas

StewardOS personas are role contracts with explicit scope, authority, and communication boundaries.

## Why this exists

Family-office workflows mix sensitive domains: money, legal structure, health, household logistics, and communication. A single unrestricted agent is high-risk and hard to audit.

Personas solve that by separating:

- who can read what,
- who can write where,
- which decisions require handoff instead of direct action.

## What is currently configured

### Persona summary

| Persona | Skills | Key MCP Servers | Contract |
|---------|--------|-----------------|----------|
| **Portfolio Manager** | 12 | portfolio-analytics, market-intel-direct, ghostfolio, policy-events, sec-edgar, household-tax, finance-graph, plane-pm | [`AGENTS.md`](../../../agent-configs/investment-officer/AGENTS.md) |
| **Research Analyst** | 5 | market-intel-direct, sec-edgar, policy-events, finance-graph, plane-pm | [`AGENTS.md`](../../../agent-configs/research-analyst/AGENTS.md) |
| **Household Comptroller** | 7 | actual, finance-graph, household-tax, ghostfolio, estate-planning, plane-pm | [`AGENTS.md`](../../../agent-configs/household-comptroller/AGENTS.md) |
| **Estate Counsel** | 7 | estate-planning, finance-graph, paperless, plane-pm | [`AGENTS.md`](../../../agent-configs/estate-counsel/AGENTS.md) |
| **Household Director** | 7 | mealie, grocy, family-edu, homebox, plane-pm | [`AGENTS.md`](../../../agent-configs/household-director/AGENTS.md) |
| **Wellness Advisor** | 6 | wger, health-graph, peloton, oura, apple-health, plane-pm | [`AGENTS.md`](../../../agent-configs/wellness-advisor/AGENTS.md) |
| **Insurance Advisor** | 4 | paperless, finance-graph, estate-planning, actual, plane-pm | [`AGENTS.md`](../../../agent-configs/insurance-advisor/AGENTS.md) |
| **Chief of Staff** | 9 | paperless, memos, google-workspace, plane-pm | [`AGENTS.md`](../../../agent-configs/chief-of-staff/AGENTS.md) |

Each persona has a contract under `agent-configs/<persona>/AGENTS.md`, plus sanitized templates in `AGENTS.example.md` and `.codex/config.toml.example`.

### Domain ownership

Each persona's authoritative domain, MCP access (read vs write), escalation rules, and boundaries are defined in its [`AGENTS.md`](../../../agent-configs/) contract. See the individual contracts linked in the table above for the precise specification.

## Persona boundary model

### Shared boundary rules

- Least privilege by default.
- Personal Google lane is read-only context.
- Outbound automation uses agent mailbox aliases (persona-specific `from_email` values).
- Tool-first operation with explicit provenance expectations.

### Email identity routing

Each persona uses a dedicated Gmail plus-address alias for outbound communication (e.g., `+io` for Portfolio Manager, `+estate` for Estate Counsel, `+hc` for Comptroller). The alias is configured in the persona's `config.toml` as the `from_email` value. Agents reply from their persona address via MCP tool calls (`google-workspace-agent-rw.reply_gmail_message`), which explicitly sets the `from_email` parameter — bypassing Gmail's default reply-from behavior. See [`docs/architecture/gmail-plus-addressing/`](../gmail-plus-addressing/README.md) for the full configuration architecture.

### Escalation decision points

Escalation is directional — each persona knows exactly which persona to hand off to and under what conditions:

- **Portfolio Manager → Household Comptroller**: any decision with material tax impact (Roth conversion, large capital gain realization, estimated payment changes).
- **Portfolio Manager → Estate Counsel**: any trade affecting entity-owned or trust-held positions.
- **Portfolio Manager → Research Analyst**: deep-dive valuations, comps analysis, DCF modeling, unit economics (delegated via Plane PM).
- **Research Analyst → Portfolio Manager**: completed research deliverables for portfolio action decisions.
- **Household Comptroller → Estate Counsel**: entity restructuring with tax implications.
- **Household Comptroller → Portfolio Manager**: portfolio-level trade decisions or risk analysis needs.
- **Estate Counsel → Household Comptroller**: estate changes with tax implications (entity dissolution, ownership transfer).
- **Estate Counsel → Portfolio Manager**: estate changes affecting portfolio-held assets.
- **Household Director → Wellness Advisor**: health-related concerns surfaced during activity or meal planning.
- **Household Director → Chief of Staff**: cross-domain coordination, calendar conflicts.
- **Wellness Advisor → Household Director**: nutrition findings that should influence meal planning.
- **Wellness Advisor → Chief of Staff**: health concerns requiring appointment scheduling.
- **Insurance Advisor → Estate Counsel**: named-insured alignment, beneficiary coordination with trust structure.
- **Insurance Advisor → Household Comptroller**: premium budget impact, claims reimbursement tracking.
- **Chief of Staff → specific persona**: any domain-specific decision routes to the owning persona.

> **Note on delegation mechanism**: Cross-persona escalation is implemented through Plane PM task delegation. Plane is the single source of truth for delegation state — there are no local delegation edges or approval machinery. The worker acts as a thin event router (session persistence + idempotency + event routing), with delegation governance enforced via system prompts and `plane-pm` tool-level `PLANE_HOME_WORKSPACE` validation.

## Workflows

See [README.md](../../../README.md#what-this-system-actually-does) for end-to-end workflow examples showing how personas compose with skills and MCP tools.

## Customization and extension

### Add or split personas

1. Create new persona directory in `agent-configs/`.
2. Add `AGENTS.example.md` and `.codex/config.toml.example`.
3. Define scope, tool access, escalation policy, and send identity.
4. Update alias routing in worker configuration.
5. Document new handoff rules to avoid scope overlap.

### Tighten boundaries

- Move tools from write to read-only access where possible.
- Require explicit escalation for high-impact operations.
- Keep write authority concentrated in one persona per system of record.

## Boundaries

- Personas define decision authority and execution limits.
- Skills define the procedural quality of persona execution.
- systemd/agent services only run those contracts; they do not replace them.
