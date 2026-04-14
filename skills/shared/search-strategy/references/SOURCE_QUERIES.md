# Source-Specific Query Translation Reference

Detailed query syntax, tool names, and filter mappings for each household data source. The agent uses this reference when translating decomposed sub-queries into source-specific API calls.

## Google Workspace (email & docs)

**Email search** (`google-workspace.search_gmail_messages`):
```
query: "property tax Maple Street"
query: "from:jim trust amendment"
```

**Drive search** (`google-workspace.search_drive_files`):
```
query: "estate plan 2025"
```

**Filter mapping:**
| User filter | Google Workspace parameter |
|-------------|---------------------------|
| `from:jim` | sender filter |
| `after:2025-01-01` | date range |
| `type:pdf` | file type filter |

## Paperless (documents)

**Document search** (`paperless.search_documents`):
```
query: "property tax bill"
correspondent: "County Assessor"
document_type: "Tax Document"
```

Good for: receipts, contracts, tax forms, insurance policies, legal documents, scanned mail.

## Actual Budget (finances)

**Financial queries** (`actual-budget.analytics`):
```
operation: "spending_by_category"
operation: "monthly_summary"
operation: "balance_history"
```

**Filter mapping:**
| User filter | Actual Budget parameter |
|-------------|------------------------|
| Category | category filter on analytics |
| Date range | start_date / end_date |
| Account | account filter |

## Estate Planning (entities/assets/dates)

**Entity/asset lookup:**
```
estate-planning.list_assets → all assets with metadata
estate-planning.list_entities → trusts, LLCs, etc.
estate-planning.get_upcoming_dates → compliance deadlines
```

## Memos (notes)

**Note search** (`memos.search_memos`):
```
query: "decision about school enrollment"
```

Good for: meeting notes, decisions, reminders, quick references.

## Homebox (inventory)

**Item search** (`homebox.list_items`):
```
query: "warranty dishwasher"
```

Good for: warranties, manuals, serial numbers, purchase history.

## Mealie & Grocy (kitchen)

**Recipe search**: `mealie.get_recipes`, `mealie.get_recipe_detailed`
**Pantry search**: `grocy.get_stock_overview`, `grocy.get_expiring_products`
