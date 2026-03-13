# StewardOS

StewardOS is a self-hosted family office agent mesh that combines:

- a local service platform (documents, budgeting, portfolio, notes, project management),
- 14 first-party MCP servers and an upstream MCP dependency layer,
- 8 role-based agent personas with explicit tool boundaries,
- 60+ reusable agent skills encoding repeatable playbooks,
- systemd-managed operational runtime with split-host mail pipeline,
- Plane-based project management as the single source of truth for task delegation.

This repository is published as a reference architecture for private, auditable household and family-office operations.

## What Makes This Different

Most MCP repositories are single-service wrappers. StewardOS focuses on orchestration across many systems with:

- explicit persona boundaries and least-privilege MCP access,
- governance-safe project management (58 Plane PM tools across 7 domain workspaces),
- Gmail plus-addressing for per-persona email identity,
- structured operating procedures encoded as versioned skills,
- self-hosted control plane with split-host deployment.

## Architecture Map

- Self-hosted software stack: [Self-Hosted Software](docs/architecture/self-hosted-software/README.md)
- MCP server layer (first-party + upstream references): [MCP Servers](docs/architecture/mcp-servers/README.md)
- Agent skills library: [Agent Skills](docs/architecture/agent-skills/README.md)
- Agent personas and policy boundaries: [Agent Personas](docs/architecture/agent-personas/README.md)
- systemd runtime and ingress topology: [systemd Runtime](docs/architecture/systemd-runtime/README.md)
- Gmail plus-addressing architecture: [Gmail Plus-Addressing](docs/architecture/gmail-plus-addressing/README.md)
- Environment configuration and incident runbook: [ENV Configuration](docs/architecture/systemd-runtime/ENV_CONFIGURATION.md)

## Repository Shape

- `services/` - containerized self-hosted software platform (Plane, Paperless, Ghostfolio, Actual Budget, and more)
- `servers/` - 14 first-party MCP servers plus paths reserved for upstream MCP checkouts
- `agent-configs/` - persona definitions and MCP wiring for 8 personas
- `agents/` - runtime ingress/worker services for automated routing, Plane polling, and scheduled execution
- `skills/` - 60+ reusable skill definitions organized by persona and shared domain
- `docs/` - architecture docs, release notes, completed plans, provisioning guides
- `docs/upstreams/` - pinned upstream/fork provenance and bootstrap metadata
- `scripts/` - bootstrap, verification, and utility scripts

## Upstream Dependency Policy

StewardOS does not vendor third-party MCP source in tracked repository content.
Use pinned references and bootstrap tooling instead:

- [Upstream Dependency Guide](docs/upstreams/README.md)
- `scripts/bootstrap_upstreams.sh`
- `scripts/verify_upstreams.sh`

## Testing

```bash
make test-all        # 411 tests across 19 projects
make lint            # ruff check
make verify-skills   # skill-to-tool contract verification
```

## Security and Sanitization

- Production secrets and runtime state are gitignored.
- Publicly tracked runtime configs are sanitized `*.example` files.
- See [SECURITY.md](SECURITY.md) for reporting and hardening expectations.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

See [ROADMAP.md](ROADMAP.md).
