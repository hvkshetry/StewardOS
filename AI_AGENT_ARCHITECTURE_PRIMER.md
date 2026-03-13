# AI Agent Architecture Primer

Last verified: 2026-03-13

This file exists to prevent a recurring failure mode for AI coding agents: assuming that `localhost` always means "local dev" and assuming that the absence of a local systemd unit means a service is not live.

In this repo, that assumption is often wrong.

## Core Mental Model

- The local machine is primarily the code-execution and automation host.
- home-server is the primary self-hosted data and app host.
- Many repo-managed MCP servers are run locally on demand, but they talk to live home-server backends through an SSH tunnel.
- Because of that tunnel, several important `localhost` ports on the local machine actually terminate on home-server.
- The mail path is split across hosts:
  - ingress webhook runs on home-server
  - worker runtime runs locally
  - home-server reaches the local worker through a reverse SSH tunnel

Short version:

- Local machine = control plane and agent runtime
- home-server = data plane and self-hosted app plane
- `localhost` can mean either one depending on the port

## What Is Actually Running Where

### Local machine: long-running services

These are active user-scoped services on the local machine:

- `family-office-mail-worker.service`
  - binds `127.0.0.1:8312`
  - runs from `agents/family-office-mail-worker`
  - this is the actual worker that generates/sends mail and runs scheduled jobs
- `home-server-db-tunnel.service`
  - maintains the SSH tunnel to home-server
  - exposes home-server services on local `localhost` ports
  - also creates the reverse tunnel from home-server back to the local mail worker
- `oci-db-tunnel.service`
  - separate tunnel to OCI shared DB
  - unrelated to the home-server personal-services topology

Important implication:

- If you change `agents/family-office-mail-worker`, the thing to restart is the local user service.
- If you change a server that only talks to `localhost:5434`, you may still be touching live home-server data even though the process runs locally.

### home-server: long-running services

These are the currently relevant live services on home-server:

- `family-office-mail-ingress.service`
  - system service
  - binds `127.0.0.1:8311`
  - runs from `$STEWARDOS_ROOT/agents/family-office-mail-ingress`
  - forwards to `WORKER_WEBHOOK_URL=http://127.0.0.1:18312/internal/family-office/gmail`
- `docker.service`
  - hosts the self-hosted app stack from `services/docker-compose.yml`
- `cloudflared.service`
  - external ingress for selected home-server services

Important implication:

- If you change `agents/family-office-mail-ingress`, the thing to redeploy/restart is the home-server system service.
- If you change `services/docker-compose.yml`, you are changing the home-server self-hosted stack, not a local-only dev environment.

### home-server: self-hosted apps exposed via Docker

The main home-server self-hosted services relevant to this repo are:

- Postgres on remote `127.0.0.1:5433`
- Paperless on remote `127.0.0.1:8223`
- Ghostfolio on remote `127.0.0.1:8224`
- Actual Budget on remote `127.0.0.1:5006`
- Memos on remote `127.0.0.1:5230`
- Homebox on remote `127.0.0.1:3100`
- Grocy on remote `127.0.0.1:9283`
- wger on remote `127.0.0.1:8280` and `127.0.0.1:8281`
- Mealie on remote `127.0.0.1:9925`
- Plane API on remote `127.0.0.1:8082`

These are defined in `services/docker-compose.yml`. The Plane stack includes 12 containers with its own Postgres 15 and Valkey 8 instances.

## SSH Tunnel Semantics

The local `home-server-db-tunnel.service` currently creates these forwards:

### Local forward: local port -> home-server port

- `127.0.0.1:5434 -> 127.0.0.1:5433`
- `127.0.0.1:8223 -> 127.0.0.1:8223`
- `127.0.0.1:8224 -> 127.0.0.1:8224`
- `127.0.0.1:9925 -> 127.0.0.1:9925`
- `127.0.0.1:9283 -> 127.0.0.1:9283`
- `127.0.0.1:8280 -> 127.0.0.1:8280`
- `127.0.0.1:5230 -> 127.0.0.1:5230`
- `127.0.0.1:3100 -> 127.0.0.1:3100`
- `127.0.0.1:5006 -> 127.0.0.1:5006`
- `127.0.0.1:8082 -> 127.0.0.1:8082`
- `127.0.0.1:8290 -> 127.0.0.1:8290`

### Reverse forward: home-server port -> local port

- `home-server 127.0.0.1:18312 -> local 127.0.0.1:8312`

Important implication:

- On the local machine, `localhost:5434` is the live home-server Postgres, not a local Postgres.
- On the local machine, `localhost:8223`, `8224`, and `5006` are home-server services via tunnel, not local containers.
- On home-server, `127.0.0.1:18312` is not a real worker process. It is the reverse-tunnel landing point for the local worker on `8312`.

## Production Meaning Of Common Ports

When running commands on the local machine, interpret these ports as follows:

| Local port | Meaning |
| --- | --- |
| `5434` | Live home-server Postgres through SSH tunnel |
| `8223` | Live home-server Paperless through SSH tunnel |
| `8224` | Live home-server Ghostfolio through SSH tunnel |
| `5006` | Live home-server Actual Budget through SSH tunnel |
| `8082` | Live home-server Plane API through SSH tunnel |
| `8312` | Local family-office mail worker |
| `8311` | Not the live ingress on the local machine; home-server owns ingress on its own loopback |

When reasoning about home-server itself:

| home-server port | Meaning |
| --- | --- |
| `5433` | home-server Docker Postgres published on loopback |
| `8311` | home-server mail ingress system service |
| `18312` | Reverse tunnel endpoint back to the local mail worker |

## Repo Services Versus Live Services

Do not assume every server in `servers/` is a long-running deployed daemon.

Current practical split:

- `agents/family-office-mail-worker`
  - live long-running local service
- `agents/family-office-mail-ingress`
  - live long-running home-server service
- `services/docker-compose.yml`
  - live home-server self-hosted stack (includes Plane)
- `services/backup-personal.sh`
  - home-server host-side backup script for the self-hosted stack
- `servers/plane-mcp`
  - governance-safe Plane PM wrapper (58 tools, 12 modules)
  - connects to Plane API via tunnel on `localhost:8082`
- `servers/finance-graph-mcp`
- `servers/health-graph-mcp`
- `servers/household-tax-mcp`
- `servers/family-edu-mcp`
- `servers/ghostfolio-mcp`
- `servers/homebox-mcp`
- `servers/grocy-mcp`
- `servers/memos-mcp`
  - repo-managed application code
  - typically run manually, in tests, or via ad hoc smoke commands
  - often connect to live home-server systems through the tunnel
  - not currently known as always-on systemd services in this environment

Important implication:

- "Not a local systemd unit" does not mean "not in production".
- It may mean "live backend is remote and the code is run ad hoc locally against it".

## Source Of Truth By Layer

| Concern | Source of truth |
| --- | --- |
| Self-hosted Postgres data | home-server `personal-db` |
| Paperless, Ghostfolio, Actual, Grocy, Homebox, Memos | home-server Docker stack |
| Plane PM (workspaces, work items, delegation) | home-server Docker stack (Plane containers) |
| Mail ingress webhook | home-server `family-office-mail-ingress.service` |
| Mail worker scheduling and send runtime | Local `family-office-mail-worker.service` |
| Task delegation and case tracking | Plane (single source of truth) |
| Repo code and MCP server source | Local checkout |

## Practical Rules For Future Agents

1. Treat `localhost:5434` as live home-server Postgres unless you have explicit proof otherwise.
2. Treat `localhost:8223`, `8224`, and `5006` as live home-server services unless you have explicit proof otherwise.
3. Treat `localhost:8312` as local-only and owned by the local mail worker.
4. Treat home-server `127.0.0.1:18312` as a reverse tunnel to the local worker, not as a remote worker process.
5. Before saying "nothing is deployed", check both:
   - local user services
   - home-server system services and Docker listeners
6. Before running integration tests against `localhost:5434`, remember that this may hit live remote data.
7. When a change touches only repo code but no long-running deployed unit, a DB migration may still affect live home-server data if the DSN points at `localhost:5434`.

## What To Restart When

- Changed `agents/family-office-mail-worker/*`
  - restart local `systemctl --user restart family-office-mail-worker.service`
- Changed `agents/family-office-mail-ingress/*`
  - redeploy/restart home-server `family-office-mail-ingress.service`
- Changed `services/docker-compose.yml` or self-hosted app config under `services/`
  - apply on home-server Docker host
- Changed MCP server code under `servers/*`
  - usually no always-on service restart is needed
  - but tests/smokes may still hit live home-server backends through the tunnel
- Changed SQL migrations for finance/health/tax/family-edu
  - assume those can affect live home-server Postgres if applied through the standard local DSNs

## Fast Verification Commands

Local machine:

- `systemctl --user list-units --type=service | rg 'family-office-mail-worker|home-server-db-tunnel|oci-db-tunnel'`
- `systemctl --user cat home-server-db-tunnel.service`
- `systemctl --user cat family-office-mail-worker.service`

home-server:

- `ssh home-server "systemctl list-units --type=service --all | egrep 'family-office-mail-ingress|cloudflared|docker'"`
- `ssh home-server "systemctl cat family-office-mail-ingress.service"`
- `ssh home-server "ss -ltnp | egrep '(:5433|:8311|:18312|:8223|:8224|:5006)'"`

## Related Repo Files

- `services/docker-compose.yml`
- `services/backup-personal.sh`
- `docs/architecture/systemd-runtime/README.md`
- `agents/family-office-mail-worker/family-office-mail-worker.service.example`
- `agents/family-office-mail-ingress/family-office-mail-ingress.service.example`

If this topology changes, update this file first. Future agents should read this file before making assumptions about what "local" means.
