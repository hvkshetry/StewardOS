---
name: search-strategy
description: Query decomposition and multi-source search orchestration. Breaks natural language questions into targeted searches per household source, translates queries into source-specific syntax, ranks results by relevance, and handles ambiguity and fallback strategies.
---

# Search Strategy

The core intelligence behind household search. Transforms a single natural language question into parallel, source-specific searches and produces ranked, deduplicated results.

## The Goal

Turn this:
```
"When does the property tax payment come due for Maple Street?"
```

Into targeted searches across every connected source:
```
google-workspace:  "property tax Maple Street due" (email search)
paperless:         "property tax" (document search, tagged with property)
estate-planning:   get_upcoming_dates (compliance/deadline lookup)
actual-budget:     analytics(operation="spending_by_category") for property tax category
```

Then synthesize the results into a single coherent answer.

## Query Decomposition

### Step 1: Identify Query Type

Classify the user's question to determine search strategy:

| Query Type | Example | Strategy |
|-----------|---------|----------|
| **Document** | "Where's the trust agreement?" | Prioritize paperless, Drive, estate-planning |
| **Financial** | "How much did we spend on groceries?" | Prioritize actual-budget, then receipts in paperless |
| **Deadline** | "When is the next filing due?" | Prioritize estate-planning dates, calendar, memos |
| **Person** | "What did Jim send us?" | Search email, paperless by correspondent |
| **Asset/Entity** | "What entities own the rental?" | Prioritize estate-planning, then supporting docs |
| **Household** | "Do we have olive oil?" | Prioritize grocy, then mealie recipes |
| **Exploratory** | "What do we know about the Greenwood application?" | Broad search across all sources |

### Step 2: Extract Search Components

From the query, extract:

- **Keywords**: Core terms that must appear in results
- **Entities**: People, properties, accounts, trusts, assets (use memory system if available)
- **Intent signals**: Deadline words, financial words, document words
- **Constraints**: Time ranges, source hints, category filters
- **Negations**: Things to exclude

### Step 3: Generate Sub-Queries Per Source

For each available source, create one or more targeted queries:

**Prefer semantic/keyword search** for:
- Conceptual questions ("What do we know about...")
- Questions where exact keywords are unknown
- Exploratory queries

**Prefer structured queries** for:
- Financial data (specific categories, date ranges, accounts)
- Entity/asset lookups (known names, types)
- Inventory checks (specific items)

**Generate multiple query variants** when the topic might be referred to differently:
```
User: "Maple Street property"
Queries: "Maple Street", "123 Maple", "maple reno", "rental property"
```

## Source-Specific Query Translation

### Google Workspace (email & docs)

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

### Paperless (documents)

**Document search** (`paperless.search_documents`):
```
query: "property tax bill"
correspondent: "County Assessor"
document_type: "Tax Document"
```

Good for: receipts, contracts, tax forms, insurance policies, legal documents, scanned mail.

### Actual Budget (finances)

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

### Estate Planning (entities/assets/dates)

**Entity/asset lookup:**
```
estate-planning.list_assets → all assets with metadata
estate-planning.list_entities → trusts, LLCs, etc.
estate-planning.get_upcoming_dates → compliance deadlines
```

### Memos (notes)

**Note search** (`memos.search_memos`):
```
query: "decision about school enrollment"
```

Good for: meeting notes, decisions, reminders, quick references.

### Homebox (inventory)

**Item search** (`homebox.list_items`):
```
query: "warranty dishwasher"
```

Good for: warranties, manuals, serial numbers, purchase history.

### Mealie & Grocy (kitchen)

**Recipe search**: `mealie.get_recipes`, `mealie.get_recipe_detailed`
**Pantry search**: `grocy.get_stock_overview`, `grocy.get_expiring_products`

## Result Ranking

### Relevance Scoring

Score each result on these factors (weighted by query type):

| Factor | Weight (Document) | Weight (Financial) | Weight (Deadline) | Weight (Exploratory) |
|--------|-------------------|--------------------|--------------------|----------------------|
| Keyword match | 0.4 | 0.2 | 0.2 | 0.3 |
| Freshness | 0.2 | 0.3 | 0.4 | 0.2 |
| Authority | 0.3 | 0.3 | 0.3 | 0.2 |
| Completeness | 0.1 | 0.2 | 0.1 | 0.3 |

### Authority Hierarchy

Depends on query type:

**For document/legal questions:**
```
Paperless (OCR'd originals) > Drive docs > Email attachments > Memos
```

**For financial questions:**
```
Actual Budget (structured data) > Paperless receipts > Email confirmations > Memos
```

**For deadline/compliance questions:**
```
Estate Planning dates > Calendar events > Email reminders > Memos
```

## Handling Ambiguity

When a query is ambiguous, prefer asking one focused clarifying question over guessing:

```
Ambiguous: "search for the application"
→ "I found references to a few applications. Are you looking for:
   1. The Greenwood Academy enrollment application
   2. The building permit application for Maple Street
   3. Something else?"
```

Only ask for clarification when:
- There are genuinely distinct interpretations that would produce very different results
- The ambiguity would significantly affect which sources to search

Do NOT ask for clarification when:
- The query is clear enough to produce useful results
- Minor ambiguity can be resolved by returning results from multiple interpretations

## Fallback Strategies

When a source is unavailable or returns no results:

1. **Source unavailable**: Skip it, search remaining sources, note the gap
2. **No results from a source**: Try broader query terms, remove date filters, try alternate keywords
3. **All sources return nothing**: Suggest query modifications to the user
4. **Rate limited**: Note the limitation, return results from other sources, suggest retrying later

### Query Broadening

If initial queries return too few results:
```
Original: "Maple Street property tax Q1 payment receipt"
Broader:  "property tax Maple"
Broader:  "property tax"
Broadest: "tax payment"
```

Remove constraints in this order:
1. Date filters (search all time)
2. Source/location filters
3. Less important keywords
4. Keep only core entity/topic terms

## Parallel Execution

Always execute searches across sources in parallel, never sequentially. The total search time should be roughly equal to the slowest single source, not the sum of all sources.

```
[User query]
     ↓ decompose
[email query] [paperless query] [budget query] [estate query] [memos query]
     ↓            ↓            ↓              ↓            ↓
  (parallel execution)
     ↓
[Merge + Rank + Deduplicate]
     ↓
[Synthesized answer]
```
