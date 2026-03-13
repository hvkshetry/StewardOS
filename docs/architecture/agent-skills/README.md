# Agent Skills

Skills are reusable operating playbooks that convert ad-hoc prompting into repeatable, reviewable workflows.

## Why this exists

StewardOS is designed for recurring household/family-office operations, not one-off chat sessions. Skills are the quality layer that makes outputs consistent over time.

- They define how a task should be executed, not just what the task is.
- They reduce behavioral drift across runs and across contributors.
- They create contribution points for domain experts (nutrition, investing, tax, legal operations, household ops).

## Skill source layers

StewardOS uses a layered skill model. The public repo tracks layers 1 and 3 directly.

### Layer 1: Repository-tracked portable skills (public, versioned)

- Location: `skills/personas/<persona>/` and `skills/shared/`
- Purpose: portable OSS baseline that contributors can review and improve.
- Tracked in git and documented in this repository.

### Layer 2: Persona-local runtime skills (private, deployment-specific)

- Location pattern: `agent-configs/<persona>/.codex/skills/`
- Purpose: persona command wrappers, operating procedures, and role-specific orchestration skills.
- Not tracked in public git by design (contains deployment-specific runtime context).

### Layer 3: Symlinked shared skills (cross-repo reuse)

In active deployments, persona skill folders may include symlinks to avoid duplicating shared skills.

Common patterns:

- `family-email-formatting` linked from each persona to the shared family-office formatting skill.
- Chief-of-staff search skills linked to a shared admin skill pack (`search`, `search-strategy`).

### Layer 4: Global toolchain skill packs (`$CODEX_HOME/skills`)

Global Codex skills are often installed as symlinks to plugin-managed skill packs (for example Anthropic example skills, Claude plugin skills, and optional knowledge/financial services skill packs).

These are environment-level capabilities and are intentionally not vendored into this repository.

## Skill composition model

Skills call MCP tools directly — they do not chain other skills. A skill is a self-contained workflow that maps trigger conditions to a sequence of tool calls, output formatting, and escalation rules. If two skills need the same data, each one calls the relevant MCP tool independently.

## What is currently configured — skill inventory (57 skills)

### Portfolio Manager (12 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `portfolio-review` | `/portfolio-review` | Full diagnostic: positions, risk (Student-t ES, illiquid overlay, vol regime), drift, TLH, recommendations |
| `rebalance` | `/rebalance` | ES-constrained rebalancing with tax-loss harvesting overlay and gate validation |
| `morning-briefing` | `/morning-briefing` | Overnight market developments, policy signals, portfolio impact assessment |
| `tax-loss-harvesting` | backend | TLH candidate identification with wash sale controls and replacement suggestions |
| `risk-model-config` | backend | Assembles illiquid overrides from finance-graph metadata for risk calculations |
| `dd-checklist` | backend | Due diligence framework for new investment evaluation |
| `client-report` | backend | Formatted client-facing portfolio report |
| `portfolio-monitoring` | backend | Ongoing illiquid/private position tracking and alert generation |
| `illiquid-valuation` | backend | Multi-method private/illiquid position valuation (comps, DCF, returns, unit-economics) |
| `investment-proposal` | backend | Tax-aware investment thesis documentation |
| `value-creation-plan` | backend | 12-24 month value creation roadmap for private holdings |
| `practitioner-heuristics` | backend | Investment practitioner mental models and decision frameworks |

> **Note on PM/RA split**: Research-intensive skills (DCF, comps, unit economics, returns analysis, market briefings) were moved to the Research Analyst persona. The Portfolio Manager delegates deep research via Plane PM task creation.

### Research Analyst (5 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `market-briefing` | `/market-briefing` | Market snapshot with macro indicators, sector analysis, and policy signals |
| `comps-analysis` | `/comps-analysis` | Comparable company analysis with peer multiples and valuation bands |
| `dcf-model` | `/dcf-model` | Discounted cash flow valuation with sensitivity analysis |
| `unit-economics` | `/unit-economics` | Customer and product-level economics analysis (LTV/CAC, margin, retention) |
| `returns-analysis` | `/returns-analysis` | IRR and MOIC sensitivity ranges for private investments |

### Chief of Staff (9 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `start` | `/start` | Daily briefing: email triage, calendar overview, expiring documents, pending alerts |
| `weekly-review` | `/weekly-review` | Aggregates tasks, documents, household status, budget alerts, and deadlines across all personas |
| `task-management` | backend | Task lifecycle management and follow-up tracking |
| `document-filing` | backend | Paperless-ngx document filing with tagging taxonomy and retention policies |
| `file-documents` | backend | Batch-file incoming documents with proper tags, correspondents, types, and titles |
| `paperless-canonical-ingestion` | backend | Cross-source ingestion: discover → deduplicate → classify → tag → upsert into Paperless |
| `memory-management` | backend | Two-tier persistent context storage for cross-session continuity |
| `household-admin` | backend | Homebox inventory management, maintenance scheduling, and household notes |
| `tax-doc-scan` | backend | Scan Paperless for tax-relevant documents, classify by tax year and category |

### Estate Counsel (7 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `estate-overview` | `/estate-overview` | Family ownership map with entity hierarchies, net worth by jurisdiction, and upcoming critical dates |
| `compliance-check` | backend | Audit entity compliance status, identify overdue filings, and flag upcoming deadlines |
| `succession-planning` | backend | Beneficiary review, distribution schedules, trust termination, and cross-border succession |
| `entity-compliance` | backend | State-specific compliance rules and filing requirements by entity type |
| `document-generation` | backend | Estate document creation using python-docx/Jinja2 templates, uploaded to Paperless |
| `contract-review` | backend | Contract analysis with obligation extraction and key date identification |
| `estate-snapshot` | backend | Point-in-time estate status for reporting or review |

### Household Director (7 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `plan-week` | `/plan-week` | Integrates meal plans, pantry state, child activities, and calendar into one weekly operational plan |
| `meal-planning` | backend | Recipe selection and weekly meal plan assembly using Mealie |
| `grocery-management` | backend | Shopping list generation from meal plans + pantry shortfalls via Grocy |
| `grocery-check` | backend | Pantry inventory monitoring — expiring items, low stock, consumption tracking |
| `activity-plan` | backend | Age-appropriate activity planning with developmental milestone context |
| `child-development` | backend | Learner profile tracking, evidence pipeline, milestone observations, term briefs |
| `household-documents` | backend | Household document filing — receipts, warranties, maintenance records, vehicle docs |

### Household Comptroller (7 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `monthly-close` | `/monthly-close` | Reconcile Actual + Ghostfolio + finance graph, persist P&L/BS/CFS line items, flag exceptions |
| `quarterly-tax` | backend | Quarterly tax analysis with estimated payment calculations and TLH coordination |
| `budget-review` | backend | Budget vs actual variance analysis with anomaly detection |
| `net-worth-report` | backend | Multi-entity net worth aggregation with liability-adjusted totals |
| `cash-forecast` | backend | Cash flow projections for 30/60/90-day horizons using recurring patterns and obligations |
| `financial-planning` | backend | Multi-period financial planning with exact 2025/2026 tax engine scenario modeling |
| `tax-form-prep` | backend | Tax form preparation checklist and document collection tracking |

### Wellness Advisor (6 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `morning-check` | `/morning-check` | Synthesizes overnight sleep data, readiness score, and workout schedule into genome-aware recovery recommendations |
| `health-dashboard` | backend | Overall health metrics aggregation across Oura, Apple Health, wger, Peloton, and health-graph |
| `weekly-health` | backend | Weekly health review correlating sleep, activity, nutrition, and body composition |
| `workout-planning` | backend | Exercise programming based on recovery status and training goals |
| `nutrition-tracking` | backend | Dietary tracking and macro analysis against nutrition plan targets |
| `medical-records` | backend | Health document management, provider tracking, and prescription monitoring |

### Insurance Advisor (4 skills)

| Skill | Trigger | Description |
|-------|---------|-------------|
| `policy-inventory` | `/policy-inventory` | Comprehensive registry of active policies, coverage limits, deductibles, premium schedules, and carrier contacts |
| `coverage-review` | `/coverage-review` | Gap analysis against asset base, liability exposure, and life events; benchmark adequacy vs industry guidelines |
| `claims-tracker` | `/claims-status` | Active and historical claims status, timeline, documentation checklist, and follow-up actions |
| `renewal-calendar` | `/renewal-calendar` | Upcoming policy renewals with comparison shopping triggers, rate history, and negotiation points |

## Skill contract

Each skill explicitly encodes:

- **Trigger conditions**: when the skill activates (user-invocable command or backend context match).
- **Tool mapping**: which MCP servers/tools are authoritative for each subtask.
- **Execution flow**: ordered steps for deterministic behavior.
- **Output format**: expected result structure and reporting shape.
- **Risk boundaries**: what to escalate, what not to do, and where to hand off.

## Current symlink status

Based on the current reference deployment:

- Public repo tracked files contain no skill symlinks.
- Runtime persona configs do use skill symlinks under `agent-configs/*/.codex/skills/`.
- `$CODEX_HOME/skills` also uses symlinked plugin-provided skill packs.

Runtime linking from tracked sources is bootstrapped with:

- `scripts/bootstrap_persona_skills.sh`

## Workflows

See [README.md](../../../README.md#what-this-system-actually-does) for end-to-end workflow examples showing how skills, personas, and MCP tools compose.

## Customization and extension

### Add a new skill

1. Create `skills/personas/<persona>/<new-skill>/SKILL.md`.
2. Document trigger conditions, tool map, workflow steps, and boundaries.
3. Add examples with realistic inputs/outputs.
4. Reference the skill in the relevant persona [`AGENTS.md`](../../../agent-configs/) contract.
5. Update docs if the skill changes architecture assumptions.

### Add a symlinked shared skill

1. Create or choose a canonical skill directory.
2. Symlink it into each persona path that should consume it (`agent-configs/<persona>/.codex/skills/<skill-name>`).
3. Confirm each consuming persona lists the skill in its `AGENTS.md` contract.
4. Keep public docs describing the pattern, but do not commit private runtime paths.

### Modify an existing skill safely

1. Keep backward-compatible output shape where possible.
2. Call out behavior changes in PR notes and examples.
3. Validate that the updated skill still respects persona authority boundaries.

For contribution guidelines, see the [Skill Contribution Guide](../../community/skill-contribution-guide.md) and [CONTRIBUTING.md](../../../CONTRIBUTING.md).

## Boundaries

- Skills define process quality and structure.
- Personas define authority and allowed tool surfaces.
- MCP servers define integration semantics and data provenance.
