# MCP Servers

StewardOS uses two MCP server classes:

- first-party servers maintained in this repository,
- upstream servers referenced via pinned commits/forks.

## First-Party MCP Servers

First-party servers in `servers/` implement domain-specific workflows (e.g., estate graph, finance graph, household tax, policy intelligence, health records).

## Upstream MCP Servers

Upstream dependencies are not vendored in tracked content.
Use:

- `docs/upstreams/upstreams.lock.yaml`,
- `scripts/bootstrap_upstreams.sh`,
- `scripts/verify_upstreams.sh`.

## Fork Policy

When upstream MCP behavior is modified for StewardOS requirements:

1. maintain a fork under the repository owner namespace,
2. keep patch commits explicit and reviewable,
3. pin fork commit SHA in lockfile,
4. prefer upstream PRs where feasible.
