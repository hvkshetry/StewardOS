# Family Office Mail Ingress

`family-office-mail-ingress` is the lightweight webhook edge for Gmail Pub/Sub push events.

## Why this service exists

It isolates external webhook reception from heavier workflow execution. The ingress service quickly acknowledges requests and forwards validated payloads to the worker.

## What it does

- Exposes `POST /webhooks/gmail`.
- Parses/validates incoming Pub/Sub envelope.
- Forwards payloads to worker endpoint with shared-secret header.
- Returns fast acknowledgment to reduce webhook retry pressure.

## Runtime defaults

- Bind: `127.0.0.1:8311`
- Worker default endpoint: `http://127.0.0.1:8312/internal/family-office/gmail`

## Environment contract

See `.env.example` for:

- host/port,
- worker target URL,
- shared secret.

## Setup

```bash
cd agents/family-office-mail-ingress
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

## systemd

Use `family-office-mail-ingress.service.example` as the render source for host units.

## Health and operations

- Keep ingress and worker on loopback unless behind trusted reverse proxy.
- Rotate shared secret when changing trust boundaries.
