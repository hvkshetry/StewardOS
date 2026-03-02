---
name: estate-snapshot
description: Full estate overview — entities, ownership graph, net worth by jurisdiction, upcoming critical dates.
user-invocable: true
---

# /estate-snapshot — Full Estate Overview

Comprehensive snapshot of the estate structure using the `estate-overview` skill workflow.

## Steps

Follow the `estate-overview` skill in full:

1. **People**: `list_people` — all family members
2. **Entities**: `list_entities(status='active')` — all active entities grouped by jurisdiction
3. **Ownership Graph**: `get_ownership_graph` — full hierarchy
4. **Assets**: `list_assets` — all assets with valuations
5. **Net Worth**: `get_net_worth` — by jurisdiction and currency
6. **Critical Dates**: `get_upcoming_dates(days=90)` — filing deadlines, renewals, reviews
7. **Document Gaps**: Identify entities/assets missing linked documents

Present the full snapshot in the format defined in the `estate-overview` skill.
Flag any anomalies: dissolved entities still owning assets, missing tax IDs, overdue dates.
