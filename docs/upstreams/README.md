# Upstream MCP Dependencies

StewardOS intentionally avoids vendoring third-party MCP server code in tracked repository content.

## Why this policy exists

- clearer license/provenance boundaries,
- easier upstream sync and patch tracking,
- reproducible dependency state via pinned commits.

## Source of truth

`upstreams.lock.yaml` defines, per dependency:

- checkout path,
- remote and upstream URLs,
- pinned commit SHA,
- optional branch reference,
- source type (`upstream` or `fork`).

## Operational workflow

- bootstrap checkouts: `scripts/bootstrap_upstreams.sh`
- verify local pins: `scripts/verify_upstreams.sh`

## Fork and patch governance

When behavior changes are needed:

1. patch in an explicit fork,
2. pin fork commit SHA in lockfile,
3. document rationale in PR/release notes,
4. upstream improvements where practical.

## Example outcome

Public users can reproduce your MCP dependency graph exactly without manually rediscovering which fork/commit combinations are known-good.
