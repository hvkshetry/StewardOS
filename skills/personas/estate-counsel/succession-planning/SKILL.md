---
name: succession-planning
description: |
  Beneficiary review, distribution schedules, trust termination conditions,
  and succession planning across US and India jurisdictions. Use when reviewing
  estate plans, updating beneficiary designations, or planning asset transfers.
---

# Succession Planning

## Scope

This skill covers:
- Beneficiary designation review across all accounts and entities
- Trust distribution schedules and termination conditions
- Asset succession paths (who inherits what, through which entities)
- Required Minimum Distribution (RMD) tracking
- Cross-border succession considerations (US + India)

## Tool Routing

- Use `estate-planning` for succession structures, beneficiary links, entity roles, ownership paths, and legal-document metadata.
- Use `finance-graph` only for valuation-history or statement-fact inputs when sizing distributions/exposure.
- Use `household-tax` for tax-impact scenario analysis tied to succession alternatives.
- Keep legal/entity updates in `estate-planning`; do not store finance-fact payloads there.

## Beneficiary Review Workflow

### Step 1: Inventory All Beneficiary-Bearing Accounts

Query estate-planning for assets that have beneficiary designations:
- Retirement accounts (IRA, 401k, Roth IRA)
- Life insurance policies
- Transfer-on-death (TOD) brokerage accounts
- Payable-on-death (POD) bank accounts
- Trust beneficiaries

### Step 2: Verify Beneficiary Designations

For each account/policy:
- Primary beneficiary: who, what percentage
- Contingent beneficiary: who, what percentage
- Last updated date
- Consistent with overall estate plan?
- Does the designation conflict with any trust provisions?

### Step 3: Flag Issues

- Missing beneficiaries (no designation on file)
- Outdated beneficiaries (ex-spouse, deceased, minor children directly)
- Inconsistencies (trust says X, account beneficiary says Y)
- Minor children named directly (should be through trust)
- No contingent beneficiary designated

## Trust Distribution Analysis

For each trust entity:

### Distribution Schedule
- What triggers distributions? (age, event, discretionary)
- Distribution amounts or percentages
- Income vs principal distribution rules
- Trustee discretion scope

### Termination Conditions
- When does the trust terminate?
- What happens to assets on termination?
- Are there any conditions that accelerate termination?

### RMD Tracking
For inherited retirement accounts held in trust:
- Annual RMD calculations based on beneficiary age
- 10-year distribution rule (SECURE Act) applicability
- Track RMDs as critical dates in estate-planning

## Succession Path Mapping

Using `get_ownership_graph`:
1. Map current ownership: Person → Entity → Entity → Asset
2. For each entity, determine succession rules:
   - Trust: beneficiary provisions
   - LLC: operating agreement transfer restrictions
   - Corp: shareholder agreement, buy-sell provisions
3. Identify gaps:
   - Assets with no clear succession path
   - Entities with no documented transfer provisions
   - Single points of failure (one person controls everything)

## Cross-Border Considerations

### US → India
- FEMA regulations on NRI property ownership
- Income from Indian assets: tax reporting on US return (FBAR, Form 8938)
- Inheritance of Indian property by US residents: no estate tax treaty
- HUF property: succession governed by Hindu Succession Act

### India → US
- US estate tax applies to worldwide assets of US persons
- Gift tax implications of transfers from India
- DTAA (Double Tax Avoidance Agreement) application
- Reporting: Form 3520 for large foreign gifts

## Output Format

```
## Succession Plan Review — [Date]

### Beneficiary Status
| Account/Policy | Primary | Contingent | Last Updated | Issues |
|---------------|---------|------------|-------------|--------|

### Trust Distribution Summary
| Trust | Distribution Trigger | Beneficiaries | Termination |
|-------|---------------------|---------------|-------------|

### Succession Gaps
- [Accounts or entities with unclear succession]
- [Documents that need updating]
- [Attorney review items]

### Action Items
1. [Specific action with deadline]
2. ...
```

## Advisory Constraints

- **Not legal advice** — flag complex succession questions for attorney review
- **Jurisdiction awareness** — always note which country's laws apply
- **Keep current** — succession plans should be reviewed annually and after major life events
- **Document everything** — link all beneficiary designations and succession documents to estate-planning
- **Provenance first** — cite which system produced each key input (estate-planning, finance-graph, household-tax)
