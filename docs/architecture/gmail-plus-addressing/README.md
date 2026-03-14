# Gmail Plus-Addressing Architecture

StewardOS uses Gmail plus-addressing (`+alias` suffixes) to give each agent persona a distinct email identity while sharing a single Gmail inbox. This document describes the full configuration: native Gmail behavior, the active filter/label/send-as layer, and how agent MCP tool calls interact with the setup.

## How Gmail Plus-Addressing Works

Gmail natively delivers mail sent to `user+anything@gmail.com` to the `user@gmail.com` inbox. No configuration is required for basic delivery — this is a built-in Gmail feature.

**However, native delivery alone is not sufficient for StewardOS.** The agent mesh requires:

1. **Inbound organization** — each persona's mail must be labeled for filtering and routing.
2. **Outbound identity** — each persona must send mail *from* its plus-address, not the base address.
3. **Agent awareness** — the mail worker must know which persona received a given message.

All three layers are actively configured. The common claim that plus-addressing requires "no changes" is misleading — it describes only the passive delivery layer, not the full two-way persona system.

## Configuration Layers

### Layer 1: Labels (8 total)

One label per persona, used as the target for inbound filters:

| Label | Persona |
|-------|---------|
| Chief of Staff | Chief of Staff |
| Estate Counsel | Estate Counsel |
| Household Comptroller | Household Comptroller |
| Household Director | Household Director |
| Portfolio Manager | Portfolio Manager |
| Research Analyst | Research Analyst |
| Insurance Advisor | Insurance Advisor |
| Wellness Advisor | Wellness Advisor |

### Layer 2: Filters (8 total)

One filter per plus-address alias. Each filter matches the `To:` header and applies the corresponding label:

| Filter (`To:` match) | Action |
|----------------------|--------|
| `steward.agent+cos@example.com` | Apply label "Chief of Staff" |
| `steward.agent+estate@example.com` | Apply label "Estate Counsel" |
| `steward.agent+hc@example.com` | Apply label "Household Comptroller" |
| `steward.agent+hd@example.com` | Apply label "Household Director" |
| `steward.agent+io@example.com` | Apply label "Portfolio Manager" |
| `steward.agent+ra@example.com` | Apply label "Research Analyst" |
| `steward.agent+insurance@example.com` | Apply label "Insurance Advisor" |
| `steward.agent+wellness@example.com` | Apply label "Wellness Advisor" |

### Layer 3: Send-As Identities (9 total)

Each plus-address is registered as a named sender identity in Gmail's "Accounts and Import" settings:

| Display Name | Address | Role |
|-------------|---------|------|
| Agent (base) | `steward.agent@example.com` | Default sender |
| Chief of Staff | `steward.agent+cos@example.com` | Persona sender |
| Estate Counsel | `steward.agent+estate@example.com` | Persona sender |
| Household Comptroller | `steward.agent+hc@example.com` | Persona sender |
| Household Director | `steward.agent+hd@example.com` | Persona sender |
| Portfolio Manager | `steward.agent+io@example.com` | Persona sender |
| Research Analyst | `steward.agent+ra@example.com` | Persona sender |
| Insurance Advisor | `steward.agent+insurance@example.com` | Persona sender |
| Wellness Advisor | `steward.agent+wellness@example.com` | Persona sender |

## Gmail Reply-From Setting vs. Agent Behavior

Gmail's "When replying to a message" setting is configured to **"Always reply from default address"** (the base `steward.agent@example.com`). This means a human hitting Reply in the Gmail UI would always send from the base address.

**Agents do not use Gmail's native reply function.** Instead, agents reply via MCP tool calls (e.g., `send_email` or `reply_to_email`) from the Google Workspace MCP server, explicitly passing the persona's plus-address as the `from` parameter. This bypasses Gmail's reply-from setting entirely.

The mechanism works because:

1. **Prompting** — each agent's system prompt (in `agent-configs/<persona>/AGENTS.md`) tells it: "Your email address is `steward.agent+<alias>@example.com`. Always reply from this address."
2. **MCP tool call** — the agent passes that address in the `from` field of the send/reply tool call.
3. **Gmail API** — the Gmail API respects the `from` field as long as the address is registered in "Send mail as" (Layer 3 above).

This produces the observed behavior: each persona replies from its own plus-address despite Gmail's UI setting preferring the default.

## Mail Worker Integration

The `family-office-mail-worker` uses the `To:` header of incoming messages to determine which persona should handle the email:

1. Gmail Pub/Sub notification arrives at ingress
2. Worker fetches the full message via Gmail API
3. Worker inspects `To:` / `Delivered-To:` headers for the plus-address suffix
4. Worker routes to the appropriate persona handler based on the alias
5. Persona handler generates a response using its skill set and MCP tools
6. Response is sent via the Google Workspace MCP `send_email` tool with the persona's plus-address as `from`

## Setup Checklist

When adding a new persona, the following Gmail changes are required:

1. **Create label** — matching the persona's display name
2. **Create filter** — `To:` matches the new plus-address, action applies the label
3. **Add send-as identity** — in Accounts and Import, add the new plus-address with the persona's display name
4. **Update agent prompt** — include the plus-address in the persona's system prompt
5. **Update worker routing** — add the alias to the mail worker's persona routing table

## Architecture Diagram

```
                    ┌─────────────────────────────────────────┐
                    │              Gmail Inbox                 │
                    │  (steward.agent@example.com)             │
                    │                                         │
                    │  ┌─ Filter: +cos ──→ Label: CoS        │
                    │  ├─ Filter: +estate → Label: Estate    │
                    │  ├─ Filter: +hc ───→ Label: HC         │
                    │  ├─ Filter: +hd ───→ Label: HD         │
                    │  ├─ Filter: +io ───→ Label: PM         │
                    │  ├─ Filter: +ra ───→ Label: RA         │
Inbound ──────────→│  ├─ Filter: +insurance → Label: Ins    │
                    │  └─ Filter: +wellness → Label: Well    │
                    └───────────────┬─────────────────────────┘
                                    │ Pub/Sub notification
                                    ▼
                    ┌───────────────────────────────┐
                    │     Mail Ingress (home-server)     │
                    │     /webhooks/gmail            │
                    └───────────────┬───────────────┘
                                    │ reverse SSH tunnel
                                    ▼
                    ┌───────────────────────────────┐
                    │     Mail Worker (local)        │
                    │                               │
                    │  1. Fetch message via Gmail API│
                    │  2. Parse To: header for alias │
                    │  3. Route to persona handler   │
                    │  4. Generate response (skills) │
                    │  5. Send via MCP tool call     │
                    │     (from: +alias address)     │
                    └───────────────┬───────────────┘
                                    │ Gmail API send
                                    ▼
                    ┌───────────────────────────────┐
Outbound ←─────────│  Gmail Send-As Identity        │
                    │  (steward.agent+alias)         │
                    └───────────────────────────────┘
```

## Common Misconceptions

| Misconception | Reality |
|--------------|---------|
| "Gmail plus-addressing needs no setup" | True for passive delivery; false for a persona system. StewardOS requires 8 labels, 8 filters, and 9 send-as identities. |
| "Replies come from the alias because Gmail auto-detects it" | No — Gmail's reply-from setting defaults to the base address. Agents bypass this via explicit MCP tool calls. |
| "Filters are optional — you can just search for `to:+alias`" | Filters ensure real-time labeling. Without them, the worker would need to poll or parse headers manually. |
| "You only need send-as for outbound" | Send-as identities also affect how replies appear in conversation threads and how recipients see the sender name. |
