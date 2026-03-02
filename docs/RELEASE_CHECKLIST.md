# Release Checklist

## Pre-Release Sanity

1. Confirm no live secrets in tracked files.
2. Confirm all sensitive production files are gitignored.
3. Confirm each required production config has a sanitized `*.example` counterpart.
4. Confirm upstream lockfile pins all external dependencies.
5. Run `scripts/verify_upstreams.sh`.

## Docs Validation

1. Root README links resolve.
2. Deep architecture READMEs are complete and consistent.
3. Roadmap reflects current migration priorities.
4. Security and contribution docs are up to date.

## Repository Hygiene

1. License present.
2. No local runtime artifacts tracked.
3. No vendored third-party source accidentally tracked.
4. Release notes summarize major architecture and boundary decisions.
