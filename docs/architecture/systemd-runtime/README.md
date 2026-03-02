# systemd Runtime

StewardOS uses systemd-managed services for host-level ingress and automation runtimes.

## Service Topology

Primary host services include:

- family-office ingress webhook service,
- local mail worker/runtime service,
- optional briefing/scheduler service,
- tunnel/edge ingress service where applicable.

## Deployment Pattern

- service unit templates are tracked as `*.service.example`,
- production units remain local and host-specific,
- deployment scripts should render user/path values per host.

## Reliability Expectations

- restart policy enabled for long-running services,
- health endpoints exposed for runtime checks,
- logs routed through journald for operational troubleshooting.
