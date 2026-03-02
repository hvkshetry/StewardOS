# MCP Servers

StewardOS uses MCP as the integration contract between agent runtimes and self-hosted/external systems.

## Server classes

- **First-party servers**: implemented in this repository for StewardOS-specific domains.
- **Upstream servers**: pinned to reviewed commits via lockfile (including forks where patches are required).

## Why this layer exists

MCP servers convert application/API complexity into stable tool interfaces that personas can consume safely and consistently.

## First-party domain coverage

Examples in this repo include:

- estate graph and planning servers,
- finance graph and tax tooling,
- portfolio analytics and policy-events servers,
- health and household domain servers.

## Upstream dependency governance

Source of truth:

- `docs/upstreams/upstreams.lock.yaml`

Operational scripts:

- `scripts/bootstrap_upstreams.sh`
- `scripts/verify_upstreams.sh`

Fork policy:

1. fork upstream under maintainer namespace,
2. keep patches explicit and reviewable,
3. pin exact commit SHA,
4. prefer upstreaming patches when feasible.

## Example

An investment persona can use:

- policy-events MCP tools for legislative/regulatory signal retrieval,
- portfolio analytics tools for exposure/risk summaries,
- ghostfolio tools for portfolio state reconciliation.
