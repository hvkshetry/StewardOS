---
name: plan-week
description: Create weekly meal plan + pantry-aware shopping list + child activities + calendar sync.
user-invocable: true
---

# /plan-week — Weekly Planning

Create a comprehensive weekly plan covering meals, groceries, child activities, and calendar.

## Steps

### 1. Meal Plan (Mealie + meal-planning skill)

Follow the `meal-planning` skill workflow:
- Gather constraints (number of people, dietary preferences, time limits)
- Select recipes balancing protein rotation, cuisine variety, effort distribution
- Build 5-7 dinner plan + optional lunches
- If using random suggestions, call `get_random_meal(date, entry_type)` with explicit args
- Present for approval

### 2. Pantry-Aware Shopping List (Grocy + grocery-management skill)

Follow the `grocery-management` skill workflow:
- Get ingredient list from meal plan recipes
- Check current pantry stock (`get_stock_overview`)
- Subtract items already in stock
- Add low-stock staples (`get_missing_products`)
- Organize list by store section

### 3. Expiring Items (Grocy)

- `get_expiring_products` (7 days) — prioritize in meal plan
- If any expiring items weren't included in the meal plan, suggest swaps

### 4. Child Activity Plan (family-edu-mcp + child-development skill)

Follow the `child-development` skill workflow:
- Check child's age and current milestones
- Plan 2-3 activities per day across 4 domains
- Balance indoor/outdoor, structured/free play
- List materials needed

### 5. Calendar Sync (Google Workspace)

- Check family calendar for the week
- Note conflicts (busy evenings → quick meals, appointments → adjust activities)
- Suggest adding meal prep times and activity blocks to calendar

### 6. Compile Plan

```
## Week of [Date]

### Meal Plan
| Day | Dinner | Prep Time | Protein | Notes |
|-----|--------|-----------|---------|-------|

### Shopping List
**Produce**: ...
**Dairy/Eggs**: ...
**Meat/Seafood**: ...
**Pantry**: ...

### Child Activities
| Day | Morning | Midday | Evening |
|-----|---------|--------|---------|

### Materials Needed
- [For activities]

### Prep Tasks (Sunday)
- [Batch cooking, meal prep, activity setup]

### Calendar Notes
- [Conflicts, adjustments]
```
