# Provisioning Guide

StewardOS provisioning is template-driven and sanitized by default: reproducible setup without leaking host- or identity-specific secrets.

## Why this exists

Provisioning scripts often contain the most sensitive operational details (hostnames, usernames, domains, token paths, service accounts).  
This guide keeps the public repository safe while still giving users a complete path to stand up their own stack.

## What is currently configured

### Provisioning templates (tracked)

- [`provisioning/deploy-host.example.sh`](../../provisioning/deploy-host.example.sh)
- [`provisioning/configure-systemd.example.sh`](../../provisioning/configure-systemd.example.sh)
- [`provisioning/stack.env.example`](../../provisioning/stack.env.example)

### Runtime/service templates (tracked)

- [`services/.env.example`](../../services/.env.example)
- `agents/*/*.service.example` unit templates
- MCP upstream lockfile: [`docs/upstreams/upstreams.lock.yaml`](../upstreams/upstreams.lock.yaml)

### Non-tracked local artifacts (by design)

- Rendered `.env` files with real credentials.
- Rendered `.service` files under `/etc/systemd/system`.
- OAuth tokens, mailbox credentials, and runtime state.

## Baseline provisioning workflow

1. Bootstrap host dependencies and repository checkout using `deploy-host.example.sh`.
2. Create local environment files from `.example` templates.
3. Start application stack via Compose.
4. Bootstrap upstream MCP repositories and verify pinned commits.
5. Render/install systemd unit files for ingress/worker/brief services.

## Practical setup sequence

### 1. Host bootstrap

```bash
cp provisioning/deploy-host.example.sh provisioning/deploy-host.sh
bash provisioning/deploy-host.sh
```

### 2. Service environment bootstrap

```bash
cp services/.env.example services/.env
# Fill values in services/.env
docker compose -f services/docker-compose.yml up -d
```

### 3. MCP dependency bootstrap

```bash
scripts/bootstrap_upstreams.sh
scripts/verify_upstreams.sh
```

### 4. systemd runtime bootstrap

```bash
cp provisioning/configure-systemd.example.sh provisioning/configure-systemd.sh
bash provisioning/configure-systemd.sh
```

## How provisioning participates in workflows

### 1. Fresh server bring-up

Provisioning creates a ready host with Compose apps, pinned MCP dependencies, and service daemons so persona workflows can run immediately after credential setup.

### 2. Update and recovery path

Template-driven setup plus lockfile pinning allows deterministic rehydration of a host after rebuild or migration.

### 3. Multi-host expansion

A second host can be bootstrapped from the same templates by changing local values only (domain, user, secrets, paths), without changing tracked repo files.

## Customization and extension

### Add new host roles

1. Create additional `*.example.sh` scripts (for example backup host, analytics host, staging host).
2. Keep placeholders generic and non-identifying.
3. Document required env vars and command prerequisites.

### Add new runtime units

1. Add `*.service.example` for each new daemon.
2. Extend `configure-systemd.example.sh` to render/install those units.
3. Keep host-specific paths/usernames as template substitutions only.

### Add new sensitive config surfaces

- Add sanitized `*.example` files.
- Ensure live files are ignored in `.gitignore`.
- Update release checklist and docs to keep the sanitization model explicit.

## Security and release hygiene

- Never commit rendered credentials, tokens, or identity-bearing host config.
- Treat `.example` files as public documentation, not private state.
- Run [`docs/RELEASE_CHECKLIST.md`](../RELEASE_CHECKLIST.md) before public pushes.
