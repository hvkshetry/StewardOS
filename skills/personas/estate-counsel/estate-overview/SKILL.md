---
name: estate-overview
description: |
  Query the estate knowledge graph for family ownership maps, entity hierarchies,
  net worth by jurisdiction, and critical dates. Use when reviewing the overall
  estate structure, preparing for attorney meetings, or checking entity status.
---

# Estate Overview

## Tool Mapping (estate-planning + finance-graph)

| Task | Tool |
|------|------|
| List family members | `estate-planning.list_people` |
| Person details + ownership | `estate-planning.get_person` |
| List entities | `estate-planning.list_entities` (filter by type, jurisdiction, status) |
| Entity details | `estate-planning.get_entity` (ownership, documents, critical dates) |
| List assets (ownership snapshot) | `estate-planning.list_assets` (filter by type, jurisdiction, owner) |
| Ownership hierarchy | `estate-planning.get_ownership_graph` (full graph or per-person transitive) |
| Net worth | `estate-planning.get_net_worth` (by person, jurisdiction, or total) |
| Critical dates | `estate-planning.get_upcoming_dates` (next N days) |
| Link document | `estate-planning.link_document` (connect Paperless doc to entity/asset) |
| Valuation history / finance facts | `finance-graph.list_valuation_observations` and related finance tools |

## Routing Boundary

- Use `estate-planning` for legal ownership, succession structure, and compliance-state reporting.
- Use `finance-graph` for valuation history and statement facts (PL/CFS/BS, XBRL/OCF).
- Do not write finance-fact payloads back into estate-planning records.
- If tax modeling is needed from this workflow, hand off to `household-tax`.

## Full Estate Snapshot Workflow

### Step 1: People

`estate-planning.list_people` — all family members with citizenship and residency status.
For each person of interest: `estate-planning.get_person` for entity ownership and linked documents.

### Step 2: Entity Hierarchy

`estate-planning.list_entities` — all trusts, LLCs, corps, HUFs with status and jurisdiction.
Group by:
- Jurisdiction (US entities vs India entities)
- Type (trusts vs operating entities vs holding entities)
- Status (active vs dissolved vs pending)

### Step 3: Ownership Graph

`estate-planning.get_ownership_graph` — full ownership hierarchy showing who owns what.
For a specific person: `estate-planning.get_ownership_graph(person_id=X)` for transitive ownership
(A owns B owns C → A effectively owns C with computed percentage).

### Step 4: Assets

`estate-planning.list_assets` — all assets with current valuation snapshots and owners.
Use `finance-graph` valuation-observation tools when trend history is needed.
Group by:
- Type (real estate, securities, bank accounts, vehicles)
- Jurisdiction
- Owner (direct person ownership vs entity ownership)

### Step 5: Net Worth

`estate-planning.get_net_worth` — aggregated by jurisdiction and currency.
For a specific person: includes both direct and indirect (through entity) ownership.

### Step 6: Critical Dates

`estate-planning.get_upcoming_dates(days=90)` — filing deadlines, renewals, distributions, reviews.
Flag overdue items (due_date < today).

## Output Format

```
## Estate Snapshot — [Date]

### Family Members
| Name | Citizenship | Residency | Tax ID Type |
|------|-------------|-----------|-------------|

### Entities (Active)
| Entity | Type | Jurisdiction | Formation | Tax ID |
|--------|------|-------------|-----------|--------|

### Ownership Graph
[Hierarchy showing person → entity → entity → asset chains]

### Net Worth by Jurisdiction
| Jurisdiction | Currency | Value | Asset Count |
|-------------|----------|-------|-------------|

### Upcoming Critical Dates (90 days)
| Date | Type | Entity/Asset | Description |
|------|------|-------------|-------------|

### Document Gaps
[Entities or assets missing linked documents]
```

## Multi-Jurisdiction Notes

### United States
- Entities: Revocable/Irrevocable Trust, LLC, S-Corp, C-Corp, LP
- Tax IDs: SSN (people), EIN (entities)
- Key formation states: DE, WY, NV (favorable laws)
- Annual requirements: state filings, franchise tax, registered agent

### India
- Entities: HUF, Private Trust, Private Ltd, LLP
- Tax IDs: PAN (people + entities), TAN (TDS deductors)
- NRI/OCI status affects: property ownership rules, FEMA compliance, tax residency
- HUF: Karta manages, ancestral property rules apply
