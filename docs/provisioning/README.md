# Provisioning Guide

StewardOS keeps **environment-specific provisioning scripts** out of source control to avoid leaking hostnames, users, domains, and credentials.

To make deployment reproducible, this repository includes sanitized templates in `provisioning/`:

- `deploy-host.example.sh` - bootstrap host packages, clone repo, and prepare runtime directories.
- `configure-systemd.example.sh` - render/install `.service` units from tracked `*.service.example` files.
- `stack.env.example` - baseline environment variables for service and MCP runtime wiring.

## How To Use

1. Copy each `*.example` file to a local, untracked file.
2. Replace placeholders (`<YOUR_USER>`, `<YOUR_DOMAIN>`, `<STEWARDOS_ROOT>`, etc.).
3. Run scripts on the target host with least privilege required.
4. Store host-specific copies in a private ops repo or secret manager.

## Security Notes

- Never commit rendered env files, real service units, tunnel credentials, or OAuth token artifacts.
- Keep deployment credentials separate from this repository.
- Re-run `docs/RELEASE_CHECKLIST.md` before any public push.
