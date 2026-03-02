# Provisioning Guide

StewardOS keeps host-specific provisioning state out of tracked public files while preserving reproducible setup through templates.

## Why this approach

Directly tracking production provisioning scripts often leaks sensitive hostnames, users, domains, or credential paths. StewardOS tracks sanitized templates instead.

## Included templates

- `provisioning/deploy-host.example.sh`
- `provisioning/configure-systemd.example.sh`
- `provisioning/stack.env.example`

## Baseline provisioning flow

1. Copy templates to local untracked files.
2. Fill host-specific values.
3. Prepare runtime directories and dependencies.
4. Render and install systemd service units from `*.service.example`.
5. Bootstrap MCP upstream checkouts and validate lockfile pins.

## Compose bootstrap

1. Copy `services/.env.example` to `services/.env`.
2. Fill secrets and domain values.
3. Start services:
   - `docker compose -f services/docker-compose.yml up -d`

## Security notes

- never track rendered env files or live credentials,
- keep token artifacts in private/local paths,
- run `docs/RELEASE_CHECKLIST.md` before public release pushes.
