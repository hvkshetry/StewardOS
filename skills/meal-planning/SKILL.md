---
name: meal-planning
description: |
  Meal planning and recipe management skill using Mealie. Use when: (1) Creating weekly meal
  plans, (2) Searching and selecting recipes, (3) Generating shopping lists, (4) Optimizing
  for nutrition and variety, (5) Planning batch cooking and meal prep, (6) Estimating meal
  costs for budget integration. Tools: mealie-mcp for all recipe and meal plan operations.
---

# Meal Planning

## Tool Mapping

| Task | Tool | Notes |
|------|------|-------|
| Search recipes | `search_recipes` | By name, tag, category, or ingredient |
| Get recipe details | `get_recipe` | Full ingredients, instructions, nutrition, prep/cook time |
| Create meal plan | `create_meal_plan_entry` | Assign recipes to dates and meal slots |
| View meal plan | `get_meal_plan` | Retrieve plan for a date range |
| Shopping list | `create_shopping_list`, `add_shopping_list_item` | Generate from meal plan |
| Manage tags/categories | `get_tags`, `get_categories` | For filtering and organization |

## Weekly Meal Plan Creation Workflow

### Step 1: Gather Constraints

Before building a plan, determine:
- Number of people eating (portion scaling)
- Days to plan (typically 5-7 dinners, optionally lunches)
- Time constraints per day (weeknight max prep time vs weekend cooking)
- Dietary restrictions or preferences active this week
- Ingredients already on hand (to use up)
- Budget target for the week (if applicable)

### Step 2: Select Recipes

Apply these balancing rules when choosing recipes for the week:

**Protein rotation** — Do not repeat the same primary protein on consecutive days:
- Cycle through: chicken, fish/seafood, legumes/lentils, eggs, paneer/tofu, lamb/mutton, pork
- Aim for at least 2 vegetarian dinners per week

**Cuisine variety** — Spread across at least 3 cuisine types per week:
- Indian (North/South), East Asian, Mediterranean, Mexican, Continental, etc.

**Effort distribution** — Match recipe complexity to day-of-week energy:
- Monday-Thursday: 30 min or less active prep
- Friday: Flexible (takeout night or simple)
- Saturday-Sunday: Can handle 45-60 min recipes, batch cooking

**Freshness sequencing** — Schedule ingredients by perishability:
- Days 1-3: Fresh fish, leafy greens, herbs
- Days 4-5: Root vegetables, frozen proteins, pantry meals
- Days 6-7: Batch-cooked leftovers, pantry/freezer meals

### Step 3: Build the Plan

1. Search Mealie for candidate recipes matching the constraints
2. Assign each recipe to a date and meal type (breakfast/lunch/dinner)
3. Use `create_meal_plan_entry` for each slot
4. Review the assembled plan for balance before presenting

### Step 4: Present for Approval

Format the plan as a table:

| Day | Dinner | Prep Time | Protein | Cuisine |
|-----|--------|-----------|---------|---------|
| Mon | Dal Tadka + Rice | 25 min | Lentils | Indian |
| Tue | Salmon Teriyaki + Stir-fry Veg | 30 min | Fish | Japanese |
| ... | ... | ... | ... | ... |

Include a notes row for any prep-ahead tasks (e.g., "Marinate chicken Tuesday night for Wednesday").

## Recipe Search and Selection

### Search Strategies

| Goal | Approach |
|------|----------|
| Use up specific ingredients | Search by ingredient name, then filter by what else is needed |
| Quick weeknight meal | Filter by tag "quick" or prep_time <= 30 min |
| Specific cuisine | Search by category or tag (e.g., "Indian", "Thai") |
| New recipe discovery | Browse categories not used in last 2 weeks |
| Kid-friendly | Filter by "kid-friendly" tag |

### When a Recipe Is Not in Mealie

1. Ask the user for the recipe source (URL, book, verbal)
2. If URL: use `create_recipe_from_url` to import
3. If manual: use `create_recipe` with full ingredients and instructions
4. Always tag and categorize the new recipe immediately after creation

## Shopping List Generation

### From Meal Plan

1. Retrieve the week's meal plan via `get_meal_plan`
2. For each recipe, pull the full ingredient list via `get_recipe`
3. Aggregate ingredients across all recipes:
   - Combine same ingredients (e.g., "2 onions" + "1 onion" = "3 onions")
   - Convert units where possible (e.g., 500ml + 250ml = 750ml)
4. Subtract pantry staples the user confirms they have
5. Create shopping list via `create_shopping_list` and add items

### Shopping List Organization

Group items by store section for efficient shopping:
- Produce (fruits, vegetables, herbs)
- Dairy and eggs
- Meat and seafood
- Pantry (grains, canned goods, spices, oils)
- Frozen
- Bakery
- Other

### Cost Estimation

When budget context is relevant:
- Estimate per-recipe cost based on ingredient quantities and approximate local prices
- Sum for weekly total
- Flag if weekly total exceeds budget target
- Suggest substitutions to reduce cost (e.g., chicken thighs vs breast, seasonal produce)

## Dietary Considerations

### Tracking Preferences

Maintain awareness of:
- Allergies (absolute restrictions — never suggest recipes containing these)
- Dietary style (vegetarian days, low-carb, etc.)
- Nutritional goals (high protein, fiber targets, etc.)
- Dislikes (strong preferences to avoid)

### Nutritional Balance Checks

For each weekly plan, verify:
- Protein source variety (not the same protein > 2x per week)
- Vegetable servings (aim for 2+ different vegetables per dinner)
- Whole grain inclusion (at least 3-4 times per week)
- Not excessive in any single category (e.g., not pasta 4 nights)

## Batch Cooking and Meal Prep

### Weekend Prep Strategy

Identify components that can be prepped ahead on Saturday/Sunday:
- **Grains**: Cook rice, quinoa, or pasta in bulk (stores 4-5 days)
- **Proteins**: Marinate or pre-cook proteins for Monday-Wednesday
- **Sauces/dressings**: Make dressings, curry bases, or marinades
- **Vegetables**: Wash, chop, and store vegetables for quick weeknight assembly
- **Legumes**: Soak and cook dried beans/lentils in bulk

### Leftover Integration

- Plan recipes that share a base component (e.g., roasted chicken Sunday -> chicken salad Monday -> chicken soup Tuesday)
- Identify recipes where doubling produces good freezer meals
- Tag recipes in Mealie as "freezer-friendly" or "meal-prep" for future reference

### Batch Cooking Presentation

When suggesting prep tasks, format as:

| Prep Task | Time | Serves Meals |
|-----------|------|-------------|
| Cook 3 cups rice | 20 min | Mon dinner, Tue lunch, Wed dinner |
| Marinate chicken thighs | 10 min | Tue dinner |
| Make tomato-onion base | 25 min | Wed dinner, Thu dinner |

## Integration with Budget Skill

When the budgeting skill is also active:
- Pull grocery budget from Actual via actual-mcp
- Compare estimated weekly meal cost against grocery budget allocation
- Track actual grocery spend vs meal plan estimate over time
- Suggest cost-saving swaps when over budget (seasonal produce, cheaper cuts, more legume meals)

## Grocy Integration (Pantry Inventory)

**Source-of-truth split:** Mealie owns recipes and meal plans. Grocy owns pantry inventory and stock-aware shopping lists.

### Pantry-Aware Shopping Lists

1. After building a meal plan, get the full ingredient list from Mealie recipes
2. Use `get_stock_overview` (grocy-mcp) to check current pantry stock
3. Subtract items already in stock from the shopping list
4. Use `get_missing_products` to add items that are below minimum stock regardless of meal plan
5. The combined list = (meal plan ingredients - pantry stock) + (low-stock items)

### Inventory Updates After Shopping

After groceries are purchased:
1. Use `add_product_to_stock` to log new items with quantities and best-before dates
2. Use `consume_product` as items are used during cooking

### Chore Integration

Use `get_chores` and `complete_chore` to track kitchen-related chores alongside meal planning:
- Fridge clean-out (weekly)
- Pantry inventory audit (monthly)
- Deep clean kitchen (bi-weekly)

## Common Pitfalls

1. **Over-ambitious weeknight recipes** — Keep Monday-Thursday to 30 min active prep max
2. **Ignoring leftovers** — Always account for planned leftovers; do not plan 7 full fresh meals if 2-3 will yield leftovers
3. **Shopping list duplicates** — Aggregate ingredients across recipes before generating the list
4. **Forgetting pantry staples** — Do not add salt, oil, and common spices to every shopping list unless the user is restocking
5. **Rigid plans** — Present the plan as a recommendation; note which days can be swapped without affecting freshness sequencing
