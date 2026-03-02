# Agent Skills

Skills are reusable operating playbooks that convert ad-hoc prompting into repeatable, reviewable workflows.

## Why this exists

StewardOS is designed for recurring household/family-office operations, not one-off chat sessions. Skills are the quality layer that makes outputs consistent over time.

- They define how a task should be executed, not just what the task is.
- They reduce behavioral drift across runs and across contributors.
- They create contribution points for domain experts (nutrition, investing, tax, legal operations, household ops).

## What is currently configured

Skills are stored under `skills/` and currently include:

- `budgeting`
- `document-management`
- `edu-planning`
- `family-email-formatting`
- `investing`
- `meal-planning`

Shared skill references and conventions live in `skills/shared/`.

## Skill contract in StewardOS

Each skill should explicitly encode:

- Trigger conditions: when the skill is required.
- Tool mapping: which MCP servers/tools are authoritative for each subtask.
- Execution flow: ordered steps for deterministic behavior.
- Output format: expected result structure and reporting shape.
- Risk boundaries: what to escalate, what not to do, and where to hand off.

## How skills participate in workflows

### 1. Household comptroller monthly close

1. Persona invokes budgeting and finance-oriented skill flows.
2. MCP data is pulled from Actual, Ghostfolio, and finance graph tools.
3. Output is emitted with variance analysis, constraints, and actionable follow-ups.

### 2. Family communications automation

1. Worker routes incoming message to persona.
2. Persona loads `family-email-formatting`.
3. Response is rendered as executive summary + deep dive + provenance.
4. Outbound send uses persona alias and structured completion JSON.

### 3. Director weekly operations loop

1. `meal-planning` builds week plan.
2. Pantry state from Grocy modifies shopping output.
3. `edu-planning` adds age-appropriate activity plan.
4. Combined digest is delivered in a consistent family-office format.

## Customization and extension

### Add a new skill

1. Create `skills/<new-skill>/SKILL.md`.
2. Document trigger conditions, tool map, workflow steps, and boundaries.
3. Add examples with realistic inputs/outputs.
4. Reference the skill in relevant persona `AGENTS.md` contracts.
5. Update docs if the skill changes architecture assumptions.

### Modify an existing skill safely

1. Keep backward-compatible output shape where possible.
2. Call out behavior changes in PR notes and examples.
3. Validate that the updated skill still respects persona authority boundaries.

## Community contribution model

StewardOS explicitly invites expert contributions to skill logic:

- Nutrition and fitness professionals for wellness workflows.
- Investment professionals for portfolio and risk playbooks.
- CPAs/bookkeepers for comptroller controls and tax procedures.
- Estate/legal operations professionals for document/entity workflows.

Contribution entry points:

- [Skill Contribution Guide](../../community/skill-contribution-guide.md)
- [CONTRIBUTING.md](../../../CONTRIBUTING.md)

## Boundaries

- Skills define process quality and structure.
- Personas define authority and allowed tool surfaces.
- MCP servers define integration semantics and data provenance.
