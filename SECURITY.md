# Security Policy

## Supported Releases

StewardOS is currently pre-1.0. Security fixes are applied on `main`.

## Reporting a Vulnerability

Please do not open public issues for suspected secrets exposure or exploitable vulnerabilities.

Report privately with:

- affected path(s),
- impact summary,
- reproduction steps,
- suggested remediation (if available).

Until a dedicated security mailbox is configured, use private GitHub communication channels on the repository owner account.

## Secret Handling Expectations

- Never commit live credentials, API keys, OAuth tokens, or personal identity artifacts.
- Keep production runtime files local and gitignored.
- Commit only sanitized `*.example` templates.
- Prefer environment variable indirection for all secrets.

## Hardening Checklist

- Rotate credentials before first public release.
- Validate no secrets are present in git history for release branches.
- Keep upstream MCP dependencies pinned to reviewed commits.
