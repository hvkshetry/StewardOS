# Environment Configuration: Ingress + Worker Split Deployment

The mail pipeline spans two hosts connected by a reverse SSH tunnel. Each service loads its own `.env` via pydantic-settings (`SettingsConfigDict(env_file=".env")`). Both `.env` files are gitignored — only `*.env.example` templates are tracked.

## Host Layout

| Service | Host | Port | systemd scope | `.env` location |
|---------|------|------|---------------|-----------------|
| `family-office-mail-ingress` | home-server (Ubuntu) | 8311 | system (`/etc/systemd/system/`) | `agents/family-office-mail-ingress/.env` |
| `family-office-mail-worker` | WSL (local laptop) | 8312 | user (`~/.config/systemd/user/`) | `agents/family-office-mail-worker/.env` |

The reverse SSH tunnel (`-R 127.0.0.1:18312:127.0.0.1:8312`) on the local machine exposes the worker to ENVY at `127.0.0.1:18312`.

## Required Variables

### Ingress (home-server)

```
SERVICE_HOST=127.0.0.1
SERVICE_PORT=8311
LOG_LEVEL=INFO
WORKER_WEBHOOK_URL=http://127.0.0.1:18312/internal/family-office/gmail
WORKER_SHARED_SECRET=<shared secret — must match worker>
PUBSUB_AUDIENCE=https://agent-mail.stewardos.example.com/webhooks/gmail
PUBSUB_SERVICE_ACCOUNT_EMAIL=pubsub-push-ingress@stewardos-gcp-project.iam.gserviceaccount.com
PLANE_WEBHOOK_SECRET=<Plane HMAC secret>
```

### Worker (local WSL)

```
PLANE_BASE_URL=http://localhost:8082
PLANE_API_TOKEN=<Plane admin PAT>
PLANE_WEBHOOK_SECRET=<Plane HMAC secret — must match ingress>
WORKER_SHARED_SECRET=<shared secret — must match ingress>
GOOGLE_CREDENTIALS_PATH=<absolute path to OAuth client JSON>
GOOGLE_TOKEN_PATH=<absolute path to token JSON>
ALLOWED_SENDERS=["principal@example.com","spouse@example.com","child1@example.com","child2@example.com"]
```

## How pydantic-settings Loads `.env`

pydantic-settings `SettingsConfigDict(env_file=".env")` reads the `.env` file from the **working directory** at import time. If the file exists but is incomplete, the missing fields silently default to their `BaseSettings` defaults (typically `""`). Environment variables set via systemd `EnvironmentFile=` or `Environment=` directives take precedence over `.env` values.

**This is the root cause of the March 2026 outage** — see below.

## Incident: Ingress 500s (2026-03-12)

### Symptoms
- All Gmail Pub/Sub webhook POSTs to `/webhooks/gmail` returned HTTP 500
- Google retried with exponential backoff, flooding logs with 500 errors
- Worker was healthy; emails eventually processed via Gmail history catch-up (not the webhook chain)

### Root Cause
While adding Plane webhook support, a partial `.env` was created on ENVY containing only `PLANE_WEBHOOK_SECRET`. pydantic-settings loaded this file and defaulted all other fields to `""`. The ingress code explicitly checks:

```python
if not settings.worker_webhook_url:
    raise HTTPException(status_code=500, detail="WORKER_WEBHOOK_URL not configured")
```

Previously, the ingress had no `.env` file at all — all required variables were injected via the systemd `EnvironmentFile=` directive pointing to the services-level `.env`. Creating a partial `.env` in the working directory caused pydantic-settings to use it as the primary source, masking the systemd-injected values.

### Fix
Populated the ENVY ingress `.env` with the complete set of required variables. Also added `WORKER_SHARED_SECRET` to the local worker `.env` (the worker validates this header on every incoming request from the ingress).

### Prevention Rules

1. **Never create a partial `.env`** — if adding a new variable to a service's `.env`, include all existing required variables. Use the tracked `.env.example` as the template.
2. **Verify health after any `.env` change** — both services expose `/health` endpoints that report configuration completeness:
   - Ingress: `worker_url_configured`, `pubsub_auth_configured`, `plane_webhook_configured`
   - Worker: `allowed_senders` count, `configured_aliases`, `watch_state_present`
3. **Restart after `.env` changes** — pydantic-settings reads `.env` at import time. Changes require a service restart.
4. **Shared secrets must match** — `WORKER_SHARED_SECRET` must be identical on both ingress and worker. The ingress sends it as `X-Family-Office-Shared-Secret` header; the worker validates it.

## Health Check Commands

```bash
# Ingress (from ENVY or via SSH)
curl -sf http://127.0.0.1:8311/health | python3 -m json.tool

# Worker (from local WSL)
curl -sf http://127.0.0.1:8312/health | python3 -m json.tool

# Worker via tunnel (from ENVY — verifies tunnel is alive)
curl -sf http://127.0.0.1:18312/health | python3 -m json.tool
```
