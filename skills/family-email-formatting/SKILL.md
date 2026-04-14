---
name: family-email-formatting
description: "Formats HTML emails with family branding and persona-specific styling, composes executive-summary briefs with KPI cards and data visualizations, drafts natural prose replies for in-thread family conversations, and applies inline CSS and provenance attribution. Use when composing outbound HTML emails for family-office personas, drafting email replies to family threads, formatting scheduled briefs or recurring reports, or sending persona-branded communications via Gmail. Supports email, draft, compose, send, reply, format, brief, and report workflows across brief and reply modes."
---

# Family Email Formatting (`brief` + `reply`)

Use this skill whenever composing outbound HTML email for family-office personas.

## Workflow

1. Determine composition mode from the caller instruction:
   - `brief` for scheduled briefs, recurring reports, and other report-style outbound emails.
   - `reply` for inbound family-email responses sent with `reply_gmail_message`.
2. Determine persona alias (`cos`, `estate`, `hc`, `hd`, `io`, `wellness`).
3. Load persona variant from `references/persona-variants.json`.
4. Render the mode-appropriate layout:
   - `brief` -> `references/base-template.md`
   - `reply` -> `references/reply-template.md`
5. Validate output: confirm no markdown leaked into HTML, persona variant matches the intended alias, and only mode-appropriate elements are present (e.g. no KPI cards in reply mode, no conversational prose structure in brief mode).
6. Compose the email using the mandatory style rules for the selected mode.

## `brief` mode

Use `brief` mode for scheduled or report-style outbound emails.

### Brief-mode structure

1. Build a two-layer response in this order:
   - Executive Summary (2-minute scan): KPI cards, action table, and an agent-chosen primary visual when warranted.
   - Deep Dive and Provenance: narrative analysis, assumptions, caveats, and source attribution.
2. Keep the executive layer compact, but make the deep dive complete enough for auditability.

### Mandatory brief-mode style rules

- Keep one shared layout for all personas.
- Apply nuance only through accent color, role label, and signature/footer copy.
- Inline styles only.
- No markdown in final body.
- Executive Summary must come before Deep Dive.
- Keep KPI cards and action-oriented summary elements for fast scanning.
- Replace the old fixed "Signal Graph" concept with one optional primary visual that best explains the key monitoring point or decision in the brief.
- The primary visual may be a spark trend, bar chart, line chart, scatter plot, progress bars, or another compact honest graphic.
- Omit the primary visual entirely when the data is too sparse or prose is clearer.
- Deep Dive must include where information came from. See Provenance Attribution section below for source citation rules.
- Do not omit narrative context when decisions or tradeoffs are involved.

### Recommended brief-mode visual hierarchy

1. Header band (role + subject + date context).
2. Executive Summary heading + one short narrative paragraph.
3. KPI strip (2 to 4 cards).
4. Action table.
5. Agent-chosen primary visual when warranted.
6. Deep Dive narrative.
7. Provenance table (claim, source system/tool, link/reference).
8. Closing and signature.

## `reply` mode

Use `reply` mode for inbound family-email responses that should read like a natural email instead of a report.

### Mandatory reply-mode style rules

- Keep the body prose-first and human-sounding.
- Make the reply read like a real human-drafted email, not a memo or artifact.
- Render the reply as actual HTML email content, not plain text pasted into an HTML body.
- Start with a natural salutation.
- When the recipient names are clear from the thread, address them naturally by name; otherwise use a warm neutral greeting.
- Open with the direct answer or key response in the first paragraph.
- Preserve the family's preference for first-principles, detailed, explanatory reasoning when the question is substantive.
- Weave reasoning into natural paragraphs instead of forcing an Executive Summary / Deep Dive split.
- Use headings only when they materially improve readability.
- Use lists, tables, or compact charts only when they communicate more clearly than prose.
- Do not force KPI cards, action boards, dashboard framing, or provenance tables into normal replies.
- End with a natural closing and persona sign-off on every reply.
- See Provenance Attribution section below for source citation rules. In reply mode, default to inline attribution.
- Inline styles only.
- No markdown in final body.
- Use real HTML structure for the body (`<p>`, `<div>`, `<table>`, `<a>`, etc.) so tables, charts, and clean clickable source links can be added when valuable.

### Recommended reply-mode visual hierarchy

1. Salutation.
2. Direct answer paragraph.
3. Supporting reasoning in natural prose.
4. Optional next steps or recommendation paragraph.
5. Natural closing and persona sign-off.
6. Optional compact table, chart, or short sources note when warranted.

## Provenance Attribution

- Prefer concrete attribution, e.g. `MCP: paperless.search_documents` or `MCP: google-workspace-personal-ro.get_events`.
- For web lookups, include direct URLs actually consulted.
- MCP-backed facts: cite MCP server/tool names in the attribution.
- Web research: include clickable HTML links to sources consulted.
- In `brief` mode, include explicit provenance in the Deep Dive narrative or a dedicated provenance table (claim, source system/tool, link/reference).
- In `reply` mode, default to inline attribution — mention the MCP server/tool parenthetically or in a short supporting clause when it materially supports the answer. Mention web sources in the prose using clean clickable HTML links when helpful. Use a final "Sources consulted" note only when the reply is research-heavy or cites enough sources that inline attribution would hurt readability.

## Pre-Send Validation

Before sending any email, the agent verifies:

- HTML renders without markdown artifacts: no `**bold**`, `_italic_`, `[links](url)`, or `# headings` in the final output.
- Persona variant loaded correctly from `references/persona-variants.json` and matches the intended alias (accent color, role label, signature copy).
- Mode-appropriate elements only: reply mode does not include brief-mode elements (KPI cards, action tables, provenance tables) and brief mode does not include reply-mode conversational structure.
- Inline styles only: no `<style>` blocks, no `<link>` tags, and no external CSS references in the final HTML body.

## Automation reply contract

- For inbound replies, use `google-workspace-agent-rw.reply_gmail_message` with the triggering Gmail `message_id`. Do not rebuild `thread_id`, `in_reply_to`, or `references` manually.
- For new outbound conversations or scheduled reports, use `google-workspace-agent-rw.send_gmail_message`.
- After the Gmail tool call, return JSON only:

```json
{"status":"sent","sent_message_id":"<id>","thread_id":"<thread_id>","from_email":"<alias_email>","to":"<recipient_or_list>"}
```
