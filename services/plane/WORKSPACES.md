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

## API Key Configuration

A single admin PAT is used for all agent writes via `plane-mcp`.
Set `API_KEY_RATE_LIMIT=300` on the `plane-api` container env to raise the default 60/min limit.

```
# In services/.env or plane-mcp env
PLANE_API_TOKEN=<admin-service-account-PAT>
PLANE_BASE_URL=http://127.0.0.1:8082
```

Each persona config references its home workspace via `PLANE_HOME_WORKSPACE` env var in `.codex/config.toml`.

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
