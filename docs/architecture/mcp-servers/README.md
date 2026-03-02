# MCP Servers

StewardOS uses MCP as the tool contract between personas/agents and the underlying software/data systems.

## Why this exists

MCP is the abstraction layer that keeps the operating model stable while applications, APIs, and providers evolve.

- Personas call tools, not raw APIs.
- Tooling is typed, auditable, and easier to test.
- Integration logic is centralized in server implementations instead of duplicated in prompts.

## What is currently configured

StewardOS currently uses a mixed server model:

- First-party domain servers in `servers/` (in-repo code, StewardOS-owned behavior).
- Upstream/forked servers pinned by commit in [`docs/upstreams/upstreams.lock.yaml`](../../upstreams/upstreams.lock.yaml).

### First-party server coverage (currently in repo)

- Estate and planning: `estate-graph-mcp`, `estate-planning-mcp`
- Finance and tax: `finance-graph-mcp`, `household-tax-mcp`
- Investment and portfolio domain: `investing-workspace`, `ghostfolio-mcp`
- Household and wellness domain: `health-records-mcp`, `wger-mcp`, `grocy-mcp`, `homebox-mcp`, `memos-mcp`, `family-edu-mcp`

### Pinned upstream/forked dependencies

The lockfile currently pins:

- `actual-mcp`
- `apple-health-mcp`
- `google-workspace-mcp`
- `mealie-mcp-server`
- `oura-mcp`
- `paperless-mcp`
- `sec-edgar-mcp`

Each entry includes remote/upstream URLs, checkout path, and exact commit SHA.

## Dependency governance and reproducibility

### Source of truth

- [`docs/upstreams/upstreams.lock.yaml`](../../upstreams/upstreams.lock.yaml)

### Operational scripts

- [`scripts/bootstrap_upstreams.sh`](../../../scripts/bootstrap_upstreams.sh): clone/fetch and checkout locked commits.
- [`scripts/verify_upstreams.sh`](../../../scripts/verify_upstreams.sh): verify local checkouts match locked SHAs.

### Fork policy

1. Fork upstream when patches are required.
2. Keep patch deltas explicit and reviewable.
3. Pin exact commit SHA in the lockfile.
4. Prefer upstreaming generic improvements to reduce long-term fork maintenance.

## How this layer participates in workflows

### 1. Investment workflow

1. `ghostfolio` and portfolio tools provide holdings/risk context.
2. `policy-events` and `sec-edgar` provide policy/disclosure context.
3. Persona composes recommendations with explicit provenance to tool calls.

### 2. Estate workflow

1. Estate counsel queries ownership/entity graph via estate servers.
2. Paperless tools provide document evidence and IDs.
3. Finance graph data can be referenced without leaking write authority across roles.

### 3. Household operations workflow

1. Mealie and Grocy tools support plan + pantry reconciliation.
2. Wellness tools combine Oura/Apple Health/wger context.
3. Chief-of-staff and household personas route outputs through shared formatting skills.

## Customization and extension

### Add a new first-party MCP server

1. Create a new server under `servers/<name>-mcp`.
2. Define stable tool names/inputs/outputs and document them in server README.
3. Add server wiring to the relevant persona config template in `agent-configs/*/.codex/config.toml.example`.
4. Update affected architecture/persona docs.

### Add or modify an upstream dependency

1. Add lock entry in [`upstreams.lock.yaml`](../../upstreams/upstreams.lock.yaml).
2. Run bootstrap and verify scripts.
3. Document why the dependency is needed and whether it is a fork.
4. If a fork is used, reference maintainer fork URL and pinned commit.

## Boundaries

- MCP servers define integration behavior and tool contracts.
- Personas define who can use which tools and under what constraints.
- Skills define procedural quality and expected output shape when tools are used.
