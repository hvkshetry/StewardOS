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

## How this layer participates in workflows

### 1. Gmail automation path

1. External push arrives at ingress endpoint.
2. Ingress validates and forwards internally to worker.
3. Worker resolves persona and invokes runtime tools.
4. Response path is written to mailbox via configured MCP servers.

### 2. Daily/weekly brief path

1. Brief service runs scheduled jobs and gathers context.
2. It invokes configured agent runtime with persona rules.
3. Output is delivered through configured communication channels.

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
- Environment loaded from local `.env` files where configured.

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
