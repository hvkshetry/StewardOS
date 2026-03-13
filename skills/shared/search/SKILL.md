---
name: search
description: Search across all connected household sources in one query. Use when the user asks to search, find, or locate information across multiple sources (email, documents, budget, inventory, estate records, recipes, pantry). Decomposes queries, runs parallel searches, ranks and deduplicates results.
---

# Search Command

Search across all connected MCP sources in a single query. Decompose the user's question, run parallel searches, and synthesize results.

## Instructions

### 1. Check Available Sources

Before searching, determine which MCP sources are available from the tool list. Household sources:

- **Email & Calendar** (via `google-workspace`) — `search_gmail_messages`, `search_drive_files`
- **Documents** (via `paperless`) — `search_documents` (OCR'd scans, receipts, legal docs)
- **Quick Notes** (via `memos`) — `search_memos`
- **Budget & Transactions** (via `actual-budget`) — `analytics(operation="monthly_summary"|"spending_by_category"|"balance_history")`
- **Inventory** (via `homebox`) — `list_items` (household items, warranties, manuals)
- **Estate & Entities** (via `estate-planning`) — `list_assets`, `list_entities`, `get_upcoming_dates`
- **Recipes** (via `mealie`) — `get_recipes`, `get_recipe_detailed`
- **Pantry** (via `grocy`) — `get_stock_overview`, `get_expiring_products`

If no MCP sources are connected:
```
To search across your tools, you'll need to connect at least one source.
Check your MCP settings to add google-workspace, paperless, actual-budget, or other tools.
```

### 2. Parse the User's Query

Analyze the search query to understand:

- **Intent**: What is the user looking for? (a document, a transaction, a recipe, an entity, a scheduled date)
- **Entities**: People, properties, accounts, assets mentioned
- **Time constraints**: Recency signals ("this week", "last month", specific dates)
- **Source hints**: References to specific systems ("in paperless", "that email", "the budget")
- **Filters**: Extract explicit filters from the query:
  - `from:` — Filter by sender/author
  - `in:` — Filter by folder, label, or category
  - `after:` — Only results after this date
  - `before:` — Only results before this date
  - `type:` — Filter by content type (email, document, receipt, recipe, transaction)

### 3. Decompose into Sub-Queries

For each available source, create a targeted sub-query:

**Google Workspace (email):**
- Use `google-workspace.search_gmail_messages` for email threads
- Translate filters: `from:` maps to sender, dates map to time range
- Use `google-workspace.search_drive_files` for documents in Drive

**Paperless (documents):**
- Use `paperless.search_documents` for OCR'd documents
- Good for: receipts, contracts, tax forms, legal documents, scanned mail
- Filter by correspondent, document type, tags

**Memos (notes):**
- Use `memos.search_memos` for quick notes and reminders
- Good for: meeting notes, decisions, ideas, reminders

**Actual Budget (finances):**
- Use `actual-budget.analytics` for financial queries
- Operations: `monthly_summary`, `spending_by_category`, `balance_history`
- Good for: "how much did we spend on X", "what's the balance of Y"

**Homebox (inventory):**
- Use `homebox.list_items` for household inventory
- Good for: warranties, manuals, serial numbers, purchase dates

**Estate Planning (entities/assets):**
- Use `estate-planning.list_assets`, `estate-planning.list_entities` for entity/asset queries
- Use `estate-planning.get_upcoming_dates` for compliance deadlines
- Good for: trust details, entity structures, filing dates

**Mealie (recipes):**
- Use `mealie.get_recipes`, `mealie.get_recipe_detailed` for recipe search
- Good for: "what can I make with X", meal planning queries

**Grocy (pantry):**
- Use `grocy.get_stock_overview`, `grocy.get_expiring_products` for pantry queries
- Good for: "do we have X", "what's expiring soon"

### 4. Execute Searches in Parallel

Run all sub-queries simultaneously across available sources. Do not wait for one source before searching another.

For each source:
- Execute the translated query
- Capture results with metadata (timestamps, authors, links, source type)
- Note any sources that fail or return errors — do not let one failure block others

### 5. Rank and Deduplicate Results

**Deduplication:**
- Identify the same information appearing across sources (e.g., a receipt in paperless AND a matching transaction in actual-budget)
- Group related results together rather than showing duplicates
- Prefer the most authoritative or complete version

**Ranking factors:**
- **Relevance**: How well does the result match the query intent?
- **Freshness**: More recent results rank higher for status/date queries
- **Authority**: Legal docs in paperless > quick notes in memos for factual questions; memos > docs for "what did we decide" queries
- **Completeness**: Results with more context rank higher

### 6. Present Unified Results

Format the response as a synthesized answer, not a raw list of results:

**For factual/document queries:**
```
[Direct answer to the question]

Sources:
- [Source 1: brief description] (paperless, document type, date)
- [Source 2: brief description] (google-workspace, email from person, date)
- [Source 3: brief description] (estate-planning, entity/asset record)
```

**For exploratory queries ("what do we know about X"):**
```
[Synthesized summary combining information from all sources]

Found across:
- Paperless: X relevant documents
- Google Workspace: X relevant emails
- Estate Planning: X related entities/assets
- [Other sources as applicable]

Key sources:
- [Most important source with reference]
- [Second most important source]
```

**For "find" queries (looking for a specific thing):**
```
[The thing they're looking for, with direct reference]

Also found:
- [Related items from other sources]
```

### 7. Handle Edge Cases

**Ambiguous queries:**
If the query could mean multiple things, ask one clarifying question before searching:
```
"the renovation" could refer to a few things. Are you looking for:
1. The Maple Street property renovation (active project)
2. The bathroom renovation completed last year
3. Something else?
```

**No results:**
```
I couldn't find anything matching "[query]" across [list of sources searched].

Try:
- Broader terms (e.g., "property" instead of "123 Maple St")
- Different time range (currently searching [time range])
- Checking if the relevant source is connected (currently searching: [sources])
```

**Partial results (some sources failed):**
```
[Results from successful sources]

Note: I couldn't reach [failed source(s)] during this search.
Results above are from [successful sources] only.
```

## Notes

- Always search multiple sources in parallel — never sequentially
- Synthesize results into answers, do not just list raw search results
- Include source attribution so users can dig deeper
- Respect the user's filter syntax and apply it appropriately per source
- When a query mentions a specific person, search for their messages/docs/mentions across all sources
- For time-sensitive queries, prioritize recency in ranking
- If only one source is connected, still provide useful results from that source
