---
name: estate-overview
description: |
  Query the estate knowledge graph for family ownership maps, entity hierarchies,
  net worth by jurisdiction, and critical dates. Use when reviewing the overall
  estate structure, preparing for attorney meetings, or checking entity status.
---

# Estate Overview

## Tool Mapping (estate-graph-mcp)

| Task | Tool |
|------|------|
| List family members | `list_people` |
| Person details + ownership | `get_person` |
| List entities | `list_entities` (filter by type, jurisdiction, status) |
| Entity details | `get_entity` (ownership, documents, critical dates) |
| List assets | `list_assets` (filter by type, jurisdiction, owner) |
| Ownership hierarchy | `get_ownership_graph` (full graph or per-person transitive) |
| Net worth | `get_net_worth` (by person, jurisdiction, or total) |
| Critical dates | `get_upcoming_dates` (next N days) |
| Link document | `link_document` (connect Paperless doc to entity/asset) |

## Full Estate Snapshot Workflow

### Step 1: People

`list_people` — all family members with citizenship and residency status.
For each person of interest: `get_person` for entity ownership and linked documents.

### Step 2: Entity Hierarchy

`list_entities` — all trusts, LLCs, corps, HUFs with status and jurisdiction.
Group by:
- Jurisdiction (US entities vs India entities)
- Type (trusts vs operating entities vs holding entities)
- Status (active vs dissolved vs pending)

### Step 3: Ownership Graph

`get_ownership_graph` — full ownership hierarchy showing who owns what.
For a specific person: `get_ownership_graph(person_id=X)` for transitive ownership
(A owns B owns C → A effectively owns C with computed percentage).

### Step 4: Assets

`list_assets` — all assets with valuations and owners.
Group by:
- Type (real estate, securities, bank accounts, vehicles)
- Jurisdiction
- Owner (direct person ownership vs entity ownership)

### Step 5: Net Worth

`get_net_worth` — aggregated by jurisdiction and currency.
For a specific person: includes both direct and indirect (through entity) ownership.

### Step 6: Critical Dates

`get_upcoming_dates(days=90)` — filing deadlines, renewals, distributions, reviews.
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
