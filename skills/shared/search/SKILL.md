---
name: search
description: Search across all connected sources in one query
---

# Search Command

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Search across all connected MCP sources in a single query. Decompose the user's question, run parallel searches, and synthesize results.

## Instructions

### 1. Check Available Sources

Before searching, determine which MCP sources are available. Attempt to identify connected tools from the available tool list. Common sources:

- **Microsoft Teams (via `office-mcp`)** — chat platform tools
- **Microsoft 365 Email (via `office-mcp`)** — email tools
- **OneDrive/SharePoint (via `office-mcp`)** — cloud storage tools
- **OpenProject (via `openproject-mcp`)** — project tracking tools
- **Twenty CRM (via `twenty-mcp`)** — CRM tools
- **Semantic Search KB (via `knowledge-base`)** — knowledge base tools

If no MCP sources are connected:
```
To search across your tools, you'll need to connect at least one source.
Check your MCP settings to add Microsoft Teams (via `office-mcp`), Microsoft 365 Email (via `office-mcp`), OneDrive/SharePoint (via `office-mcp`), or other tools.

Supported sources: Microsoft Teams (via `office-mcp`), Microsoft 365 Email (via `office-mcp`), OneDrive/SharePoint (via `office-mcp`), OpenProject (via `openproject-mcp`), Twenty CRM (via `twenty-mcp`), Semantic Search KB (via `knowledge-base`),
and any other MCP-connected service.
```

### 2. Parse the User's Query

Analyze the search query to understand:

- **Intent**: What is the user looking for? (a decision, a document, a person, a status update, a conversation)
- **Entities**: People, projects, teams, tools mentioned
- **Time constraints**: Recency signals ("this week", "last month", specific dates)
- **Source hints**: References to specific tools ("in Microsoft Teams (via `office-mcp`)", "that email", "the doc")
- **Filters**: Extract explicit filters from the query:
  - `from:` — Filter by sender/author
  - `in:` — Filter by channel, folder, or location
  - `after:` — Only results after this date
  - `before:` — Only results before this date
  - `type:` — Filter by content type (message, email, doc, thread, file)

### 3. Decompose into Sub-Queries

For each available source, create a targeted sub-query using that source's native search syntax:

**Microsoft Teams (via `office-mcp`):**
- Use available search and read tools for your chat platform
- Translate filters: `from:` maps to sender, `in:` maps to channel/room, dates map to time range filters
- Use natural language queries for semantic search when appropriate
- Use keyword queries for exact matches

**Microsoft 365 Email (via `office-mcp`):**
- Use available email search tools
- Translate filters: `from:` maps to sender, dates map to time range filters
- Map `type:` to attachment filters or subject-line searches as appropriate

**OneDrive/SharePoint (via `office-mcp`):**
- Use available file search tools
- Translate to file query syntax: name contains, full text contains, modified date, file type
- Consider both file names and content

**OpenProject (via `openproject-mcp`):**
- Use available task search or typeahead tools
- Map to task text search, assignee filters, date filters, project filters

**Twenty CRM (via `twenty-mcp`):**
- Use available CRM query tools
- Search across Account, Contact, Opportunity, and other relevant objects

**Semantic Search KB (via `knowledge-base`):**
- Use semantic search for conceptual questions
- Use keyword search for exact matches

### 4. Execute Searches in Parallel

Run all sub-queries simultaneously across available sources. Do not wait for one source before searching another.

For each source:
- Execute the translated query
- Capture results with metadata (timestamps, authors, links, source type)
- Note any sources that fail or return errors — do not let one failure block others

### 5. Rank and Deduplicate Results

**Deduplication:**
- Identify the same information appearing across sources (e.g., a decision discussed in Microsoft Teams (via `office-mcp`) AND confirmed via email)
- Group related results together rather than showing duplicates
- Prefer the most authoritative or complete version

**Ranking factors:**
- **Relevance**: How well does the result match the query intent?
- **Freshness**: More recent results rank higher for status/decision queries
- **Authority**: Official docs > wiki > chat messages for factual questions; conversations > docs for "what did we discuss" queries
- **Completeness**: Results with more context rank higher

### 6. Present Unified Results

Format the response as a synthesized answer, not a raw list of results:

**For factual/decision queries:**
```
[Direct answer to the question]

Sources:
- [Source 1: brief description] (Microsoft Teams (via `office-mcp`), #channel, date)
- [Source 2: brief description] (Microsoft 365 Email (via `office-mcp`), from person, date)
- [Source 3: brief description] (OneDrive/SharePoint (via `office-mcp`), doc name, last modified)
```

**For exploratory queries ("what do we know about X"):**
```
[Synthesized summary combining information from all sources]

Found across:
- Microsoft Teams (via `office-mcp`): X relevant messages in Y channels
- Microsoft 365 Email (via `office-mcp`): X relevant threads
- OneDrive/SharePoint (via `office-mcp`): X related documents
- [Other sources as applicable]

Key sources:
- [Most important source with link/reference]
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
"API redesign" could refer to a few things. Are you looking for:
1. The REST API v2 redesign (Project Aurora)
2. The internal SDK API changes
3. Something else?
```

**No results:**
```
I couldn't find anything matching "[query]" across [list of sources searched].

Try:
- Broader terms (e.g., "database" instead of "PostgreSQL migration")
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
