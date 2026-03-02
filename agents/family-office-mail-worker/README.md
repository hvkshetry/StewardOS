# Family Office Mail Worker

Local codex-only worker for family-office email automation.

## What it does
- Accepts forwarded Gmail Pub/Sub payloads at `POST /internal/family-office/gmail`
- Enforces sender allowlist (family members only)
- Detects recipient `+alias` and maps to the matching persona config
- Persists session continuity per alias+thread (`gmail:{alias}:{thread_or_message}`)
- Processes all new messages in a history window (paginated)
- Invokes persona Codex in `--full-auto` mode with directory sandbox semantics
- Requires persona to send reply via Gmail MCP and return JSON send acknowledgment
- Tracks durable idempotency by inbound Gmail message ID to prevent duplicate replies
- Auto-renews Gmail watch when expiration is near
- Runs three scheduled skill-driven briefs (if enabled):
  - IO Monday pre-market (06:00 ET)
  - IO Friday post-close (18:00 ET)
  - COS Monday weekly priorities (07:00 ET)

## Ports
- Default bind: `127.0.0.1:8312` (chosen to avoid conflicts with existing services)

## Local setup
```bash
cd ~/personal/agents/family-office-mail-worker
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

## Initialize Gmail watch cursor
```bash
cd ~/personal/agents/family-office-mail-worker
.venv/bin/python scripts/setup_watch.py
```

Run this once before expecting Pub/Sub webhook events. The service auto-renews watch state thereafter.

## Scratch directory
- Default temporary workspace: `/tmp/family-office-mail-worker`
- Used for short-lived artifacts (for example attachment prep) during automated runs

## Scheduled brief skill chains
- IO pre-market: `morning-briefing` -> `portfolio-review` (light) -> `family-email-formatting`
- IO post-close: `portfolio-review` -> `tax-loss-harvesting` (conditional) -> `rebalance` (conditional) -> `family-email-formatting`
- COS weekly priorities: `weekly-review` -> `task-management` (read-only summary) -> `family-email-formatting` -> `search-strategy`/`search` (conditional)

## systemd (local machine)
```bash
sudo cp family-office-mail-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now family-office-mail-worker
sudo systemctl status family-office-mail-worker --no-pager
```
