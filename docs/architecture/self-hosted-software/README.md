# Self-Hosted Software

StewardOS runs a consolidated local software stack via Docker Compose.

## Platform Services

Core components include:

- PostgreSQL and Redis infrastructure,
- document management,
- budgeting and finance apps,
- portfolio tracking,
- notes/knowledge capture,
- household inventory and pantry systems,
- workflow automation and data orchestration.

## Runtime Characteristics

- services are loopback-bound by default,
- health checks are defined for critical services,
- resource limits are explicitly set in compose definitions,
- external exposure is expected through controlled ingress.

## Operational Notes

- service-specific credentials are configured via local `.env` files (gitignored),
- public templates are provided via `services/.env.example`,
- backup and retention strategy is documented in service scripts.
