---
name: activity-plan
description: Create weekly age-appropriate child activities balanced across developmental domains.
user-invocable: true
---

# /activity-plan — Weekly Child Activities

Plan a week of age-appropriate developmental activities.

## Steps

### 1. Child Profile (family-edu-mcp)

- `get_child_profile` — age, preferences, current focus areas
- `get_milestones` — current milestone status across domains

### 2. Identify Focus Areas

- Milestones that are "emerging" or "not started" for the child's age
- Domains needing more attention this week
- Activities the child enjoyed recently (engagement anchors)

### 3. Select Activities

Follow the `child-development` skill:
- 2-3 structured activities per day
- Balance across cognitive, physical, creative, social-emotional
- At least 3 outdoor activities per week
- At least 1 completely new activity for novelty
- Include at least 1 activity the child loves (engagement anchor)

### 4. Build Weekly Plan

| Day | Morning (Cognitive/Creative) | Midday (Physical) | Evening (Social/Creative) |
|-----|----------------------------|-------------------|--------------------------|

### 5. Prepare Materials List

- Consolidated list of everything needed for the week
- Note what needs to be purchased vs what's on hand
- Prep-ahead tasks (e.g., freeze paint, prep sensory bin)

### 6. Output

```
## Activity Plan — Week of [Date]

### [Child Name] — Age: X years, Y months

### Focus Areas
- [Domain]: [Specific milestone or skill]

### Weekly Plan
| Day | Morning | Midday | Evening |
|-----|---------|--------|---------|

### Materials Needed
- [ ] ...

### Flexibility Notes
- [Which activities can be swapped]
- [Rainy day alternatives]
```

Create the plan in family-edu-mcp via `create_weekly_plan`.
