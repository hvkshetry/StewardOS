# Agent Personas

StewardOS personas are role contracts with explicit scope, authority, and communication boundaries.

## Why this exists

Family-office workflows mix sensitive domains: money, legal structure, health, household logistics, and communication. A single unrestricted agent is high-risk and hard to audit.

Personas solve that by separating:

- who can read what,
- who can write where,
- which decisions require handoff instead of direct action.

## What is currently configured

Current persona roster:

- Chief of Staff
- Estate Counsel
- Household Comptroller
- Household Director
- Investment Officer
- Wellness Advisor

Each persona has a contract under `agent-configs/<persona>/AGENTS.md`, plus sanitized templates in `AGENTS.example.md` and `.codex/config.toml.example`.

## Persona boundary model

### Shared boundary rules

- Least privilege by default.
- Personal Google lane is read-only context.
- Outbound automation uses agent mailbox aliases (persona-specific `from_email` values).
- Tool-first operation with explicit provenance expectations.

### Domain ownership (current operating model)

- Comptroller: canonical owner of household budget, monthly close, and tax-operating workflows.
- Investment Officer: portfolio/risk/research workflows with binding risk guardrails.
- Estate Counsel: entity/ownership/legal-operational graph and document-linked estate workflows.
- Household Director: meal, pantry, education planning, and household logistics.
- Wellness Advisor: sleep/activity/workout/medical-record aggregation and wellness trend analysis.
- Chief of Staff: triage, routing, briefs, and cross-domain coordination.

## How personas participate in workflows

### 1. Inbound family-office mail

1. Ingress receives Gmail Pub/Sub push.
2. Worker resolves alias to persona contract.
3. Persona executes within its tool and scope boundaries.
4. Reply is sent with persona identity and structured completion contract.

### 2. Cross-domain decision flow

Example: proposed large portfolio rebalance with tax implications.

1. Investment Officer runs strategy and risk analysis.
2. Household Comptroller validates household tax/cashflow impact.
3. Estate Counsel is engaged only if entity/ownership effects are present.
4. Chief of Staff can synthesize final action brief for execution.

### 3. Household operations weekly plan

1. Household Director produces plan (meals, pantry, activities).
2. Wellness Advisor adds recovery/fitness context.
3. Chief of Staff packages summary for calendar and communication cadence.

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
