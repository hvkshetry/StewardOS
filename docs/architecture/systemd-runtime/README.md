# systemd Runtime

StewardOS uses systemd-managed services for host-level ingress and automation runtimes.

## Service Topology

Primary host services include:

- **family-office-mail-ingress** — FastAPI webhook for Gmail Pub/Sub and Plane webhooks (home-server, system scope)
- **family-office-mail-worker** — FastAPI worker that processes inbound email, generates replies, runs Plane poller, and executes scheduled jobs (local machine, user scope)
- **family-brief-agent** — scheduled briefing/scheduler service (optional)
- **home-server-db-tunnel** — SSH tunnel connecting local machine to home-server services
- **cloudflared** — Cloudflare tunnel for external ingress (home-server)

## Mail Pipeline

The mail pipeline is split across two hosts:

1. Gmail Pub/Sub pushes notifications to Cloudflare tunnel
2. **Ingress** (home-server) validates OIDC tokens, extracts history IDs, forwards to worker via reverse SSH tunnel
3. **Worker** (local machine) fetches full messages from Gmail API, routes to persona-specific handlers, generates replies via MCP tool calls

The worker also runs:
- **Plane poller** — polls Plane work items for case completion and delegation events
- **Plane webhook handler** — receives forwarded Plane webhooks from ingress (HMAC-SHA256 verified)
- **Scheduled jobs** — APScheduler-driven briefings and maintenance tasks loaded from `agents/schedules.yaml`

## Deployment Pattern

- service unit templates are tracked as `*.service.example`,
- production units remain local and host-specific,
- deployment scripts should render user/path values per host.

## Reliability Expectations

- restart policy enabled for long-running services,
- health endpoints exposed for runtime checks (see [ENV Configuration](ENV_CONFIGURATION.md)),
- logs routed through journald for operational troubleshooting.

## Related Documentation

- [AI Agent Architecture Primer](../../../AI_AGENT_ARCHITECTURE_PRIMER.md) — split-host topology, port mappings, what-to-restart-when
- [ENV Configuration](ENV_CONFIGURATION.md) — required env vars, pydantic-settings behavior, incident runbook
- [Plane Workspaces](../../../services/plane/WORKSPACES.md) — workspace domain taxonomy
