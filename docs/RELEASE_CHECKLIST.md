# Release Checklist

## Pre-Release Sanity

1. Confirm no live secrets in tracked files.
2. Confirm all sensitive production files are gitignored.
3. Confirm each required production config has a sanitized `*.example` counterpart.
4. Confirm upstream lockfile pins all external dependencies.
5. Run `scripts/verify_upstreams.sh`.
6. Run sync script leak scanner: `python scripts/sync_to_public.py --verify-only --worktree <path>`.

## Testing

1. `make test-all` — all 411 tests pass.
2. `make lint` — ruff check clean.
3. `make verify-skills` — skill-to-tool contracts valid.

## Docs Validation

1. Root README links resolve.
2. All 7 architecture READMEs are complete and consistent:
   - self-hosted-software, mcp-servers, agent-skills, agent-personas, systemd-runtime, gmail-plus-addressing, ENV_CONFIGURATION
3. Persona count and names match across: README, agent-personas, agent-skills, skill-contribution-guide.
4. MCP server inventory matches across: README, mcp-servers, skill-contribution-guide.
5. Roadmap reflects current phase completion status.
6. Security and contribution docs are up to date.
7. Release notes written for current sync.

## Repository Hygiene

1. License present.
2. No local runtime artifacts tracked.
3. No vendored third-party source accidentally tracked.
4. Release notes summarize major architecture and boundary decisions.
5. Completed plans archived in `docs/completed-plans/`.
