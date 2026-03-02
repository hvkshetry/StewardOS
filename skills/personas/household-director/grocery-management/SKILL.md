---
name: grocery-management
description: |
  Grocy pantry inventory management skill. Use when: (1) Checking what's expiring,
  (2) Generating pantry-aware shopping lists, (3) Logging products after shopping,
  (4) Tracking stock levels, (5) Managing barcodes and product database.
  Tools: grocy-mcp for all inventory operations.
---

# Grocery Management

## Tool Mapping

| Task | Tool | Notes |
|------|------|-------|
| Current stock | `get_stock_overview` | All products with quantities and expiry |
| Product details | `get_stock_item` | Full details for one product |
| Expiring soon | `get_expiring_products` | Products expiring within N days |
| Missing/low stock | `get_missing_products` | Products below minimum stock level |
| Add to stock | `add_product_to_stock` | Log purchased items with best-before |
| Consume product | `consume_product` | Reduce stock when item is used |
| Barcode lookup | `get_product_by_barcode` | Find product by scanning barcode |
| Add by barcode | `add_by_barcode` | Quick add using barcode |
| Open product | `open_product` | Mark as opened (affects shelf life) |
| Transfer | `transfer_product` | Move between locations (pantry, fridge, freezer) |
| Shopping list | `get_shopping_list` | Current shopping list |
| Auto-fill list | `add_missing_to_shopping_list` | Add all below-minimum products |
| Locations | `list_locations` | Pantry, fridge, freezer, etc. |

## Expiration Management

### Daily Check
1. `get_expiring_products` with days=3 — what needs to be used today/tomorrow
2. Suggest recipes from Mealie that use expiring ingredients
3. Flag items past best-before for discard decision

### Weekly Review
1. `get_expiring_products` with days=7 — plan the week around what's expiring
2. Prioritize expiring items in meal plan suggestions
3. Surface items with no best-before date that have been in stock > 30 days

## Shopping List Workflow

### Pantry-Aware List (coordinates with meal-planning skill)

1. Get meal plan ingredient list from Mealie
2. `get_stock_overview` — check current pantry stock
3. Subtract items already in stock (sufficient quantity)
4. `get_missing_products` — add items below minimum regardless of meal plan
5. Combined list = (meal plan needs - pantry stock) + low-stock items

### After Shopping

1. `add_product_to_stock` for each purchased item
   - Include best-before date, purchase price, store
   - Use barcode scanning when possible (`add_by_barcode`)
2. Clear purchased items from shopping list
3. `transfer_product` if items go to different locations (fridge vs pantry)

## Stock Organization

### Location Strategy
- **Pantry**: Dry goods, canned items, spices, oils
- **Fridge**: Dairy, fresh produce, leftovers, opened sauces
- **Freezer**: Frozen proteins, batch-cooked meals, bread, frozen veg
- **Counter**: Fruit bowl, onions, garlic, tomatoes

### Minimum Stock Levels

Track minimum quantities for staples:
- Cooking oil, rice, pasta, flour, sugar, salt
- Milk, eggs, butter, cheese
- Onions, garlic, ginger, tomatoes
- Spices (cumin, turmeric, chili, coriander)

When below minimum, automatically add to shopping list.

## Chore Integration

Use `get_chores` and `complete_chore` for kitchen-related recurring tasks:
- Fridge clean-out (weekly)
- Pantry audit and rotation (monthly)
- Freezer inventory check (monthly)
- Spice cabinet review (quarterly)
