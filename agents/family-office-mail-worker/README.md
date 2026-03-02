# Family Office Mail Worker

`family-office-mail-worker` is the automation runtime that routes inbound messages to persona-specific agent execution.

## Why this service exists

It provides deterministic, policy-bound automation for family-office email workflows while preserving persona boundaries and thread continuity.

## Core capabilities

- Receives webhook payloads at `POST /internal/family-office/gmail`.
- Enforces sender allowlist.
- Maps recipient `+alias` to persona config.
- Preserves session continuity per alias + thread.
- Runs scheduled brief workflows.
- Requires explicit send acknowledgment contract from persona execution.

## Typical workflow

1. Ingress forwards Pub/Sub event.
2. Worker validates sender and deduplicates message processing.
3. Worker resolves alias -> persona.
4. Worker invokes agent runtime.
5. Persona sends response through configured Gmail MCP path.
6. Worker records execution metadata.

## Runtime defaults

- Bind: `127.0.0.1:8312`
- Scratch dir: `/tmp/family-office-mail-worker`
- SQLite metadata DB: local file path via env

## Environment contract

See `.env.example` for:

- allowlist and mailbox identity,
- alias-to-persona map,
- agent runtime command configuration,
- schedule recipients and cron windows.

## Setup

```bash
cd agents/family-office-mail-worker
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

Initialize watch cursor once before live inbound processing:

```bash
.venv/bin/python scripts/setup_watch.py
```

## systemd

Use `family-office-mail-worker.service.example` as render source for host units.

## Contribution opportunities

- stronger idempotency behavior,
- richer failure routing/retry policy,
- backend adapters for additional agent runtimes,
- scheduling quality-of-service improvements.
