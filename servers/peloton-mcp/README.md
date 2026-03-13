# peloton-mcp

Read-only MCP wrapper for Peloton workout data plus a strict usefulness gate probe.

## Environment

- `PELOTON_API_BASE_URL` (default: `https://api.onepeloton.com`)
- `PELOTON_OAUTH_CLIENT_ID` (recommended)
- `PELOTON_OAUTH_REFRESH_TOKEN` (recommended)
- `PELOTON_OAUTH_CLIENT_SECRET` (optional; required for confidential OAuth clients)
- `PELOTON_OAUTH_TOKEN_URL` (default: `https://auth.onepeloton.com/oauth/token`)
- `PELOTON_OAUTH_AUDIENCE` (default: `https://api.onepeloton.com/`)
- `PELOTON_OAUTH_SCOPE` (default: `openid offline_access`)
- `PELOTON_OAUTH_REFRESH_SKEW_SEC` (default: `60`)
- `PELOTON_OAUTH_TOKEN_STORE_PATH` (optional, recommended; persists rotated refresh tokens)
- `PELOTON_REQUIRE_OAUTH` (default: `0`; set `1` to hard-disable bearer/session/username fallbacks)
- `PELOTON_BEARER_TOKEN` (optional fallback/debug)
- `PELOTON_SESSION_ID` (optional override)
- `PELOTON_USERNAME`
- `PELOTON_PASSWORD` (legacy fallback only; currently deprecated on many tenants)
- `PELOTON_PLATFORM` (default: `web`)
- `PELOTON_TIMEOUT_SEC` (default: `30`)

Auth precedence:
1. OAuth refresh-token flow (`PELOTON_OAUTH_CLIENT_ID` + `PELOTON_OAUTH_REFRESH_TOKEN`) -> short-lived access token.
2. Static bearer token (`PELOTON_BEARER_TOKEN`).
3. Session cookie (`PELOTON_SESSION_ID`).
4. Legacy username/password login to `/auth/login`.

## PKCE Bootstrap (one-time)

1. Generate authorize URL and PKCE verifier:

```bash
python scripts/peloton_oauth.py start-pkce \
  --client-id "$PELOTON_OAUTH_CLIENT_ID" \
  --redirect-uri "https://members.onepeloton.com/"
```

2. Open `authorize_url` in browser, complete login, capture returned `code`.

3. Exchange `code` for access/refresh tokens:

```bash
python scripts/peloton_oauth.py exchange-code \
  --client-id "$PELOTON_OAUTH_CLIENT_ID" \
  --redirect-uri "https://members.onepeloton.com/" \
  --code "<AUTH_CODE>" \
  --code-verifier "<CODE_VERIFIER>" \
  --token-store-path "$STEWARDOS_ROOT/agent-configs/wellness-advisor/.codex/peloton-oauth-token.json"
```

4. Store the returned `refresh_token` in secret storage and set `PELOTON_OAUTH_REFRESH_TOKEN`.
5. Set `PELOTON_OAUTH_TOKEN_STORE_PATH` so rotated refresh tokens are persisted across process restarts.

## Tools

- `peloton_auth_diagnostics`
- `peloton_get_workouts(start_date, end_date, limit=50, page=0, user_id="")`
- `peloton_get_workout_detail(workout_id, joins=...)`
- `peloton_get_performance_graph(workout_id, every_n_seconds=1)`
- `peloton_get_class_metadata(ride_id)`

## Usefulness gate

Run before production rollout:

```bash
python scripts/probe_peloton_value.py --start-date 2025-12-01 --end-date 2026-03-01 --sample-size 20
```

Gate pass criteria:
- Detail and performance-graph success rates each `>= 0.90`
- At least `4` additive metric families (cadence, power, resistance, output, class metadata, instructor)

If the gate fails, do not enable this MCP in the wellness advisor config.
