# systemd Runtime

StewardOS uses systemd for long-running agent-facing services (ingress, worker, scheduled briefing) while Compose handles the application stack.

## Why this exists

The runtime needs always-on daemons with predictable restart behavior, host-native logging, and boot-time recovery.

systemd is used because it provides:

- stable lifecycle management for Python/uvicorn processes,
- restart policies and failure containment,
- `journalctl` observability for service-level debugging,
- clean separation from containerized data applications.

## What is currently configured

Tracked service templates:

- [`agents/family-office-mail-ingress/family-office-mail-ingress.service.example`](../../../agents/family-office-mail-ingress/family-office-mail-ingress.service.example)
- [`agents/family-office-mail-worker/family-office-mail-worker.service.example`](../../../agents/family-office-mail-worker/family-office-mail-worker.service.example)
- [`agents/family-brief-agent/family-brief-agent.service.example`](../../../agents/family-brief-agent/family-brief-agent.service.example)

Template rendering/installation is automated by:

- [`provisioning/configure-systemd.example.sh`](../../../provisioning/configure-systemd.example.sh)

### Runtime topology

- Ingress service binds loopback `:8311` and validates webhook envelopes.
- Worker service binds loopback `:8312` and executes persona workflows.
- Brief service binds loopback `:8300` for scheduled/context brief generation.
- Compose-hosted systems remain separate and are consumed through MCP/tool calls.

### Gmail automation path

The full email automation pipeline works as follows:

1. **Gmail Pub/Sub push** delivers a notification to the ingress endpoint (`:8311`).
2. **Ingress validates the envelope signature** (Google Cloud Pub/Sub message authentication) and rejects invalid payloads.
3. **Ingress forwards the validated message** internally to the worker service (`:8312`).
4. **Worker extracts the recipient alias** from the incoming message headers (e.g., `investment-officer@<domain>`).
5. **Worker resolves the persona** by loading the contract from `agent-configs/<alias>/AGENTS.md` and runtime config from `agent-configs/<alias>/.codex/config.toml`.
6. **Worker executes within persona boundaries** — the persona's MCP server access, skill set, and escalation rules are enforced.
7. **Worker replies via `google-workspace-mcp`** using the persona's configured `from_email` alias and structured completion contract.

### Scheduled briefing path

1. Brief service runs cron-triggered jobs at configured intervals.
2. It invokes the configured agent runtime with persona rules (e.g., Investment Officer for morning briefings, Chief of Staff for weekly reviews).
3. Output is delivered through configured communication channels (email, memos).

### Environment management

Each systemd service loads its runtime configuration from a local `.env` file via the systemd `EnvironmentFile=` directive. Template `.env` files are rendered by the provisioning script (`provisioning/configure-systemd.example.sh`) during deployment, replacing placeholder values with deployment-specific secrets and paths.

### Dependency ordering

systemd services require the Docker Compose application stack to be running — Compose services provide the data plane that MCP servers connect to. The systemd units use `After=network.target` but do not declare explicit Compose dependencies; operators should ensure `docker compose up -d` completes before starting agent services.

## Workflows

See [README.md](../../../README.md#autonomous-agent-runtime) for end-to-end workflow examples showing how the agent runtime executes persona-scoped workflows.

## Operations and observability

Typical commands (host):

```bash
sudo systemctl status family-office-mail-ingress
sudo systemctl status family-office-mail-worker
sudo systemctl status family-brief-agent
sudo journalctl -u family-office-mail-worker -n 200 --no-pager
```

Expected operational posture:

- `Restart=always` for core daemons.
- Loopback binds by default.
- Environment loaded from local `.env` files via `EnvironmentFile=` directive.

## Customization and extension

### Add a new runtime daemon

1. Add app code under `agents/<service-name>/`.
2. Create `<service-name>.service.example` with placeholder user/paths.
3. Extend provisioning template script to render/install the new unit.
4. Document port, health endpoint, and failure behavior.

### Harden runtime boundaries

- Run as dedicated non-root system user.
- Keep public ingress through a controlled reverse proxy only.
- Add health probes and lightweight smoke checks for each service.

## Boundaries

- systemd runtime manages process lifecycle only.
- It does not define persona behavior, skill logic, or tool access policy.
- Those contracts remain in `agent-configs/`, `skills/`, and MCP server configs.
