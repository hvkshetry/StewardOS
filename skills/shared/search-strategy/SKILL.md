---
name: search-strategy
description: "Query decomposition and multi-source search orchestration for household information systems. Breaks natural language questions into targeted per-source searches, translates queries into source-specific syntax (Gmail, Paperless, Actual Budget, estate planning, memos, inventory), ranks and deduplicates results across sources, and handles fallback when sources return nothing or are unavailable. Use when searching across multiple household systems (email, documents, finances, estate records, inventory, memos), finding information spanning different data sources, or answering questions that require synthesizing results from several systems. Trigger terms: search, find, look up, query across sources."
---

# Search Strategy

The core intelligence behind household search. Transforms a single natural language question into targeted, source-specific searches and produces ranked, deduplicated results.

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

Each household source has its own query syntax, tool names, and filter parameters. The table below summarizes which tool to use for each source. For full syntax details, filter mappings, and example queries, see [references/SOURCE_QUERIES.md](references/SOURCE_QUERIES.md).

| Source | Primary Tool | Best For |
|--------|-------------|----------|
| Google Workspace | `search_gmail_messages`, `search_drive_files` | Email threads, shared documents, attachments |
| Paperless | `search_documents` | Receipts, contracts, tax forms, scanned mail |
| Actual Budget | `analytics` | Spending, balances, category breakdowns |
| Estate Planning | `list_assets`, `list_entities`, `get_upcoming_dates` | Trusts, LLCs, compliance deadlines |
| Memos | `search_memos` | Meeting notes, decisions, quick references |
| Homebox | `list_items` | Warranties, manuals, serial numbers |
| Mealie & Grocy | `get_recipes`, `get_stock_overview` | Recipes, pantry inventory, expiring items |

## Result Ranking

### Decision Rules by Query Type

Rather than abstract scoring weights, the agent follows concrete ranking rules based on query type:

**For document/legal questions:**
1. Surface Paperless OCR'd originals first (authoritative source of record)
2. Then Drive docs (may be working copies or summaries)
3. Then email attachments (may be older versions)
4. Memos last (references only, not source documents)

**For financial questions:**
1. Surface Actual Budget structured data first (authoritative numbers)
2. Then Paperless receipts (supporting documentation)
3. Then email confirmations (transaction records)
4. Memos last (notes about financial decisions)

**For deadline/compliance questions:**
1. Surface Estate Planning dates first (tracked compliance deadlines)
2. Then calendar events (scheduled reminders)
3. Then email reminders (may contain date references)
4. Memos last (noted deadlines)

**For exploratory questions:**
Return results from all sources grouped by source and let the user decide which thread to follow. Present each source group with a brief summary of what was found.

## Result Verification

Before presenting results to the user, perform these verification steps:

1. **Deduplication**: Check whether the same document appears in multiple sources (e.g., a PDF found both as an email attachment in Gmail and as an archived document in Paperless). Merge duplicate entries and note the canonical source.
2. **Relevance filtering**: Drop results that have no keyword overlap with the original query or its extracted entities. A result that matched only on metadata (e.g., date range) without any topical connection should be excluded.
3. **Completeness check**: Note which sources returned no results and briefly explain why (e.g., "No matching memos found" or "Actual Budget has no transactions in the specified category"). This helps the user understand gaps rather than assuming silence means no information exists.

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

## Sequential Execution Strategy

Tool calls are executed sequentially, not in parallel. To minimize latency and provide faster answers, the agent should order source queries strategically based on the query type classification:

1. **Query the most likely source first** based on query type (see Step 1 above). For example, a financial question hits Actual Budget before searching email.
2. **If the first source returns a confident answer**, present it immediately while noting that additional sources can be checked for confirmation.
3. **If the first source returns partial or no results**, proceed to the next most likely source in priority order.
4. **For exploratory queries**, start with the broadest source (email or Paperless) and work toward narrower sources.

```
[User query]
     ↓ classify query type
     ↓ determine source priority order
[Source 1 query] → evaluate results
     ↓ (if insufficient)
[Source 2 query] → evaluate results
     ↓ (if insufficient)
[Source 3 query] → evaluate results
     ↓
[Merge + Rank + Deduplicate + Verify]
     ↓
[Synthesized answer]
```
