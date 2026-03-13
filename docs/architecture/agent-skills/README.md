# Agent Skills

StewardOS skills encode repeatable playbooks for recurring tasks. Skills are organized by persona (persona-specific) and by domain (shared across personas).

## Skill Design

Each skill should define:

- scope and trigger conditions,
- tool usage expectations (which MCP tools to call and in what order),
- data quality and provenance requirements,
- output format constraints.

## Skill Organization

### Persona-Specific Skills (`skills/personas/<persona>/`)

| Persona | Key Skills | Notes |
|---------|-----------|-------|
| Chief of Staff | task-management, memory-management, document-filing, household-admin, tax-doc-scan, orchestration-patterns | Cross-persona routing matrix, complexity scoring |
| Estate Counsel | estate-overview, entity-compliance, document-generation, succession-planning, contract-review | Python-docx + Jinja2 templates for doc generation; multi-jurisdiction (US + India) |
| Household Comptroller | financial-planning, quarterly-tax, monthly-close, budget-review, cash-forecast, net-worth-report, tax-form-prep, tax-orchestration | Exact TY2025 US+MA tax engine with AMT, child tax credit, safe harbor planning |
| Household Director | meal-planning, grocery-management, child-development, household-documents | CDC milestone tracking; source-of-truth split (Mealie meals vs Grocy pantry) |
| Portfolio Manager | portfolio-review, rebalance, tax-loss-harvesting, client-report, investment-proposal, illiquid-valuation, portfolio-monitoring, value-creation-plan, dd-checklist, risk-model-config, practitioner-heuristics | Hard gates: ES<=2.5% (97.5% CI), illiquidity<=25% NW, employer concentration<=15% |
| Research Analyst | market-briefing, comps-analysis, dcf-model, unit-economics, returns-analysis | Research only — no portfolio management or trading recommendations |
| Insurance Advisor | policy-inventory, coverage-review, claims-tracker, renewal-calendar | Cross-references finance-graph assets and estate-planning entities for coverage adequacy |
| Wellness Advisor | health-dashboard, workout-planning, nutrition-tracking, medical-records, morning-check, weekly-health | Genome-aware via health-graph (PGx, clinical assertions, Tier 1-4 findings); recovery-aware scheduling |

### Shared Skills (`skills/shared/`)

- **orchestration-patterns** — cross-persona routing matrix, complexity scoring, multi-agent synthesis
- **search / search-strategy** — cross-source retrieval and query decomposition
- **family-email-formatting** — HTML email templates with `brief`/`reply` modes and persona-specific visual variants

### Cross-Domain Skills (`skills/`)

- **budgeting** — budget analysis and variance utilities
- **document-management** — document filing and taxonomy
- **investing** — investment analysis and research utilities

## Governance

- skills should be role-appropriate — a persona should only invoke skills within its domain,
- skills must not bypass persona boundaries or access tools outside their persona's MCP set,
- skills should not embed live secrets or personal identifiers,
- skill-to-tool contract is verified by `make verify-skills` (CI-enforced).
