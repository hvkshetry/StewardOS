# systemd Runtime

StewardOS supports host-level service management with systemd for agent ingress/worker processes and related operational daemons.

## Why systemd is used

Agent runtimes often need stable long-lived processes, controlled restart behavior, and journald-native observability.

## Typical services

- family-office ingress webhook service,
- mail worker automation service,
- family brief scheduler service,
- optional host edge/tunnel services.

## Public deployment pattern

- tracked unit templates: `*.service.example`
- rendered host units: local-only (not tracked)
- host path/user values are substituted at deployment time

## Reliability and operations

- restart policies enabled,
- health endpoints used for smoke checks,
- logs collected via journald.

## Example

A host can run Compose for platform applications while running agent ingress/worker via systemd to keep runtime isolation and easier lifecycle control.
