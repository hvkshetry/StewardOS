# MCP Server Bug Log

Last updated: 2026-02-26

## Scope
- Servers under test: `grocy`, `mealie`, `paperless`, `family-edu`, `deepwiki`
- Goal: smoke test read/write operations and record reproducible issues

## Running Bug List
None currently.

## Resolved / Environment Issues
1. **RESOLVED** - Global `401` auth failures across all three servers.
   - Resolution: set credentials in `.codex/config.toml` and restart session/servers.
   - Resolved on: 2026-02-26

2. **RESOLVED** - `paperless` success-path tools returned `Unexpected response type`.
   - Resolution: tool handlers now return MCP-compliant `content` payloads (updated runtime build files and source).
   - Verification: `list_tags`, `list_document_types`, `search_documents`, `create_tag` return structured text content successfully.
   - Resolved on: 2026-02-26

3. **RESOLVED** - `mealie.get_random_meal` route/method mismatch.
   - Resolution: updated tool contract to `get_random_meal(date, entry_type)` and switched to `POST /api/households/mealplans/random`.
   - Verification: repeated successful calls with explicit `date` and `entry_type`.
   - Resolved on: 2026-02-26

4. **RESOLVED** - `mealie.create_recipe` failed with server 500.
   - Resolution: `update_recipe` now uses `PUT`, and create/update recipe flows update full recipe payload with normalized ingredient/instruction sections.
   - Verification: `create_recipe(name=\"MCP Smoke Recipe PostFix 2026-02-26 v10\", ingredients=[\"1 cup water\"], instructions=[\"Boil water.\"])` succeeded; follow-up `update_recipe` and `get_recipe_detailed` succeeded.
   - Resolved on: 2026-02-26

5. **RESOLVED** - `paperless.delete_tag` failed with `Unexpected end of JSON input`.
   - Resolution: `PaperlessAPI.request` now handles empty/204 responses safely and only parses JSON when body exists.
   - Verification: `create_tag` -> `delete_tag` returns `{\"result\":\"OK\"}`; `list_tags` confirms deletion.
   - Resolved on: 2026-02-26

6. **RESOLVED** - `family-edu` started without seeded activity/milestone catalogs.
   - Symptom: `get_activities_for_age(...)` returned `[]`; `get_milestones(child_id=...)` returned `[]`.
   - Resolution: updated `servers/family-edu-mcp/server.py` to auto-seed activities and milestones at startup and seed milestones in `add_child`.
   - Verification after restart:
     - `get_activities_for_age(age_months=24)` returned populated activities.
     - `get_milestones(child_id=1)` and `get_milestones(child_id=2)` returned full milestone lists.
     - New child creation (`id=3`) immediately had seeded milestones.
   - Resolved on: 2026-02-26

## Test Calls Executed
- `grocy` (working): `get_stock_overview`, `get_missing_products`, `get_expiring_products`, `list_locations`, `get_chores`, `get_shopping_list`, `add_missing_to_shopping_list`
- `grocy` (expected validation/domain errors): `get_product_by_barcode` with unknown barcode (`400`), `get_stock_item` with non-existent product (`400`)
- `mealie` (working): `get_recipes`, `list_categories`, `list_tags`, `get_shopping_lists`, `parse_ingredient`, `create_mealplan`, `get_todays_mealplan`, `get_all_mealplans`, `list_cookbooks`
- `mealie` (expected not-found/validation errors): `get_recipe_detailed` unknown slug (`404`), `get_recipe_concise` unknown slug (`404`), `add_to_shopping_list` with non-UUID list id (`422`)
- `mealie` (bugs): `create_recipe` (`500 ValidationError`), `get_random_meal` (`422 int_parsing`)
- `paperless` (tool-layer bug): `list_tags`, `list_correspondents`, `list_document_types`, `list_saved_views`, `search_documents`, `create_tag`, `create_correspondent`, `create_document_type`
- `paperless` (normal HTTP error return observed): `get_document`, `get_document_metadata`, `get_document_suggestions`, `delete_tag` with non-existent id (`404`)
- `mealie` (fixed): `get_random_meal(date, entry_type)`, `create_recipe`, `update_recipe`
- `paperless` (fixed): `list_tags`, `list_document_types`, `search_documents`, `create_tag`
- `paperless` (working additional CRUD): `create_correspondent`, `bulk_edit_correspondents(operation=\"delete\")`, `create_document_type`, `bulk_edit_document_types(operation=\"delete\")`, `update_tag`, `delete_tag`
- `mealie` (working additional flows): `create_mealplan_bulk`, `get_all_mealplans`, `create_recipe`, `update_recipe`, `get_recipe_concise`, `get_recipe_detailed` (for newly created recipe)
- `mealie` (environment/data issue): `get_recipe_concise` / `get_recipe_detailed` return backend `500 ValidationError` for some legacy corrupted recipe slugs created before fixes
- `family-edu` (working): `add_child`, `create_weekly_plan`, `get_weekly_plan`, `add_journal_entry`
- `family-edu` (bug): `get_activities_for_age`, `get_milestones` returned empty catalog data (see Running Bug List)
- `deepwiki` (working): `read_wiki_structure`, `read_wiki_contents`, `ask_question`
