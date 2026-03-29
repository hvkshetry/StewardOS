# Plane Workspaces — Domain Taxonomy

7 domain-scoped workspaces. Named by domain, not persona.
Future persona splits stay within existing workspaces.

| Workspace Slug | Domain | Current Persona(s) | Labels |
|----------------|--------|-------------------|--------|
| `chief-of-staff` | Operations & administration | Chief of Staff | `case`, `agent-task`, `human-task` |
| `estate-counsel` | Legal, entities, succession | Estate Counsel | `case`, `agent-task`, `human-task` |
| `household-finance` | Cash, budget, tax, statements | Household Comptroller | `case`, `agent-task`, `human-task` |
| `household-ops` | Meals, grocery, child dev | Household Director | `case`, `agent-task`, `human-task` |
| `investment-office` | Portfolio, markets, research | Portfolio Manager, Research Analyst | `case`, `agent-task`, `human-task` |
| `wellness` | Health, fitness, nutrition, medical | Wellness Advisor | `case`, `agent-task`, `human-task` |
| `insurance` | Policies, claims, coverage | Insurance Advisor | `case`, `agent-task`, `human-task` |

## Agent Identities

Plane should treat agents as first-class collaborators, not one shared automation user.
Create one Plane user and one PAT per active agent persona:

| Persona | Plane User | Email |
|---------|------------|-------|
| Chief of Staff | `Chief of Staff Agent` | `steward.agent+cos@example.com` |
| Estate Counsel | `Estate Counsel` | `steward.agent+estate@example.com` |
| Household Comptroller | `Household Comptroller` | `steward.agent+hc@example.com` |
| Household Director | `Household Director` | `steward.agent+hd@example.com` |
| Portfolio Manager | `Portfolio Manager` | `steward.agent+io@example.com` |
| Research Analyst | `Research Analyst` | `steward.agent+ra@example.com` |
| Wellness Advisor | `Wellness Advisor` | `steward.agent+wellness@example.com` |
| Insurance Advisor | `Insurance Advisor` | `steward.agent+insurance@example.com` |

Initial human collaborators:

| Human | Email |
|-------|-------|
| Principal Family | `principal@example.com` |
| Spouse Singh | `spouse@example.com` |

Each persona config should carry its own `PLANE_API_TOKEN` and `PLANE_HOME_WORKSPACE`.
Keep `PLANE_BASE_URL=http://127.0.0.1:8082` consistent across personas.

## Validation

- Fast remote API smoke: `bash $STEWARDOS_ROOT/services/plane/smoke-test-api-v1.sh`
- Remote Postgres-backed contract test:
  `bash $STEWARDOS_ROOT/services/plane/run-contract-tests-remote.sh`
- Optional test override:
  `TEST_PATH=plane/tests/contract/api/test_coordination.py bash $STEWARDOS_ROOT/services/plane/run-contract-tests-remote.sh`

## Workspace Setup Checklist

For each workspace:
1. Create workspace in Plane UI
2. Create default labels: `case`, `agent-task`, `human-task`
3. Create at least one default project per workspace

## Cross-Domain Rules

- Lead agent always owns the root case in its home workspace
- Cross-domain work: lead agent creates a task in the target workspace
- No agent creates cases outside its home workspace without human approval
- Cross-domain tasks carry `delegated_by` and `origin_workspace` labels
