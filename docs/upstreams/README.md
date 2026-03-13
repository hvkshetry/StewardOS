# Upstream MCP Dependencies

StewardOS references external MCP servers through pinned commits.

## Why This Exists

- avoids long-term vendoring overhead,
- preserves provenance and licensing clarity,
- makes local environments reproducible.

## Source of Truth

`upstreams.lock.yaml` contains:

- local checkout path,
- source repository URL,
- pinned commit SHA,
- optional source branch reference for fork-only patch streams,
- patch source (`upstream` or `fork`).

## Workflows

- bootstrap local checkouts: `scripts/bootstrap_upstreams.sh`
- verify checkouts match pins: `scripts/verify_upstreams.sh`

## Patch Governance

If StewardOS requires behavior changes to upstream MCP servers:

1. fork upstream,
2. commit patch to fork,
3. pin fork commit in lockfile,
4. reference fork URL in this document and lockfile.
