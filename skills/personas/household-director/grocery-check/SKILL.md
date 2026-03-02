---
name: grocery-check
description: Check expiring products, low stock items, and generate shopping list from current meal plan.
user-invocable: true
---

# /grocery-check — Pantry & Shopping Check

Quick check of pantry status and shopping needs.

## Steps

### 1. Expiring Products (Grocy)

- `get_expiring_products` with days=3 — needs to be used today/tomorrow
- `get_expiring_products` with days=7 — plan into this week's meals
- Present with location and suggested action (use, freeze, discard)

### 2. Low Stock (Grocy)

- `get_missing_products` — items below minimum stock level
- Group by category (staples, dairy, produce, etc.)

### 3. Current Meal Plan Needs (Mealie)

- `get_all_mealplans` for the current week
- For each remaining planned meal: use `get_recipe_detailed` for ingredient list
- Cross-reference with current stock

### 4. Generate Shopping List

- Combine: meal plan needs + low stock + expiring-item replacements
- Subtract: items currently in stock at sufficient quantity
- Organize by store section

### 5. Output

```
## Grocery Check — [Date]

### Expiring Soon (Use First!)
| Product | Expires | Location | Action |
|---------|---------|----------|--------|

### Low Stock
| Product | Current | Minimum | Need |
|---------|---------|---------|------|

### Shopping List
**Produce**: ...
**Dairy/Eggs**: ...
**Meat/Seafood**: ...
**Pantry**: ...

### Total Items: X
```
