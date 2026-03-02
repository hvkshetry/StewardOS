---
name: family-email-formatting
description: |
  Generate family-office HTML emails with a two-layer format: executive summary first, then deep-dive narrative with provenance. Use this before sending any outbound HTML email from family personas.
---

# Family Email Formatting (Executive Summary + Deep Dive)

Use this skill whenever composing outbound HTML email for family-office personas.

## Workflow

1. Determine persona alias (`cos`, `estate`, `hc`, `hd`, `io`, `wellness`).
2. Load persona variant from `references/persona-variants.json`.
3. Render layout from `references/base-template.md`.
4. Build a two-layer response in this order:
   - Executive Summary (2-minute scan): KPI cards, action table, and signal graph.
   - Deep Dive and Provenance: narrative analysis, assumptions, caveats, and source attribution.
5. Keep the executive layer compact, but make the deep dive complete enough for auditability.

## Mandatory style rules

- Keep one shared layout for all personas.
- Apply nuance only through accent color, role label, and signature/footer copy.
- Inline styles only.
- No markdown in final body.
- Executive Summary must come before Deep Dive.
- Deep Dive must include where information came from:
  - MCP-backed facts: cite MCP server/tool names.
  - Web research: include links actually consulted.
- Do not omit narrative context when decisions or tradeoffs are involved.

## Recommended visual hierarchy

1. Header band (role + subject + date context).
2. Executive Summary heading + one short narrative paragraph.
3. KPI strip (2 to 4 cards).
4. Action table.
5. Signal graph/progress bars.
6. Deep Dive narrative.
7. Provenance table (claim, source system/tool, link/reference).
8. Closing and signature.

## Provenance guidance

- Prefer concrete attribution, e.g. `MCP: paperless.search_documents` or `MCP: google-workspace-personal-ro.get_calendar_events`.
- For web lookups, include direct URLs.
- If no web sources were used, explicitly state that in the deep-dive or provenance section.

## Automation reply contract

After sending with Gmail tools, return JSON only:

```json
{"status":"sent","sent_message_id":"<id>","thread_id":"<thread_id>","from_email":"<alias_email>","to":"<recipient_or_list>"}
```
