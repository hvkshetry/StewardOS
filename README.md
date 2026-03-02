# StewardOS

StewardOS is a self-hosted family office agent mesh that combines:

- a local service platform (documents, budgeting, portfolio, notes, workflow automation),
- custom and upstream MCP servers,
- role-based agent personas,
- reusable agent skills,
- systemd-managed operational runtime.

This repository is published as a reference architecture for private, auditable household and family-office operations.

## What Makes This Different

Most MCP repositories are single-service wrappers. StewardOS focuses on orchestration across many systems with:

- explicit persona boundaries,
- role-specific tool access,
- structured operating procedures,
- self-hosted control plane and deployment practices.

## Architecture Map

- Self-hosted software stack: [Self-Hosted Software](docs/architecture/self-hosted-software/README.md)
- MCP server layer (first-party + upstream references): [MCP Servers](docs/architecture/mcp-servers/README.md)
- Agent skills library: [Agent Skills](docs/architecture/agent-skills/README.md)
- Agent personas and policy boundaries: [Agent Personas](docs/architecture/agent-personas/README.md)
- systemd runtime and ingress topology: [systemd Runtime](docs/architecture/systemd-runtime/README.md)
- host provisioning templates and deployment workflow: [Provisioning Guide](docs/provisioning/README.md)

## Repository Shape

- `services/` - containerized self-hosted software platform
- `servers/` - first-party MCP servers plus paths reserved for upstream MCP checkouts
- `agent-configs/` - persona definitions and MCP wiring (sanitized `*.example` only)
- `agents/` - runtime ingress/worker services for automated routing and scheduled execution
- `skills/` - reusable skill definitions used by personas and automation flows
- `docs/upstreams/` - pinned upstream/fork provenance and bootstrap metadata

## Upstream Dependency Policy

StewardOS does not vendor third-party MCP source in tracked repository content.
Use pinned references and bootstrap tooling instead:

- [Upstream Dependency Guide](docs/upstreams/README.md)
- `scripts/bootstrap_upstreams.sh`
- `scripts/verify_upstreams.sh`

## Security and Sanitization

- Production secrets and runtime state are gitignored.
- Publicly tracked runtime configs are sanitized `*.example` files.
- See [SECURITY.md](SECURITY.md) for reporting and hardening expectations.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

See [ROADMAP.md](ROADMAP.md).
