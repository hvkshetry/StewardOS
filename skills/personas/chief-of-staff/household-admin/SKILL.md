---
name: household-admin
description: |
  Household administration skill covering Homebox inventory management,
  maintenance scheduling, and Memos for household notes and decisions.
  Use when tracking household items, warranties, maintenance, or capturing
  household-related notes.
---

# Household Admin

## Homebox Inventory

### Tool Mapping

| Task | Tool |
|------|------|
| Browse items | `list_items` (filter by location, tag, label) |
| Item details | `get_item` (full details, custom fields, attachments) |
| Add item | `create_item` (name, location, tags, purchase info) |
| Update item | `update_item` (modify any field) |
| Location tree | `get_location_tree` (hierarchical view) |
| Maintenance log | `get_item_maintenance`, `add_maintenance_entry` |
| Statistics | `get_group_statistics`, `get_purchase_price_stats` |
| Asset lookup | `lookup_asset` (by asset ID barcode) |
| Import/Export | `import_items_csv`, `export_items_csv` |

### When Adding New Items

Capture at minimum:
- **Name**: Clear, specific (e.g., "Samsung 65-inch TV" not "TV")
- **Location**: Room and specific spot (e.g., "Living Room > TV Stand")
- **Purchase date**: For warranty and depreciation tracking
- **Purchase price**: For insurance and replacement cost estimates
- **Tags**: Category tags (electronics, furniture, kitchen, tools, etc.)

If applicable also capture:
- **Warranty expiry**: Set so we can surface expiring warranties
- **Serial number**: For insurance claims
- **Model/manufacturer**: For replacement parts and support

### Maintenance Scheduling

Use `add_maintenance_entry` to log:
- HVAC filter changes (every 3 months)
- Appliance deep cleans (quarterly)
- Smoke detector battery replacement (annually)
- Pest control treatments (quarterly/annually)

Surface upcoming maintenance via `list_all_maintenance`.

## Memos for Household Notes

### Tool Mapping

| Task | Tool |
|------|------|
| Create note | `create_memo` |
| Search notes | `search_memos` |
| List recent | `list_memos` |
| Update note | `update_memo` |

### What to Capture in Memos

- Household decisions (contractor quotes, renovation plans)
- Service provider notes (plumber, electrician, HVAC — names, contact, quality)
- Home improvement ideas and priorities
- Recurring household issue tracking
- Guest preferences and visit notes

### Memo Tagging

Use `#tags` in memo content for categorization:
- `#maintenance` — home maintenance notes
- `#renovation` — improvement projects
- `#provider` — service provider contacts and reviews
- `#decision` — household decisions made
- `#idea` — future improvement ideas
