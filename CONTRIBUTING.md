# Contributing to StewardOS

## Development Model

This repository is an integration architecture. Contributions should prioritize:

- clear boundaries between persona capabilities,
- safe defaults for self-hosted deployments,
- reproducible MCP dependency pinning,
- documented operational behavior.

StewardOS is maintained with a private-first workflow and curated public publishing. Public contributions should remain fully sanitized and reproducible.

## Getting Started

1. Clone the repository.
2. Copy required `*.example` files to local runtime equivalents.
3. Bootstrap upstream MCP dependencies:
   - `scripts/bootstrap_upstreams.sh`
4. Verify pinned checkouts:
   - `scripts/verify_upstreams.sh`

## Sensitive Files

Do not commit:

- live `.env` files,
- runtime `.codex` state,
- OAuth credential/token files,
- local database or log artifacts.

Use sanitized `*.example` files.

## Pull Request Guidelines

- Keep changes scoped and documented.
- Update architecture docs when behavior or boundaries change.
- Include migration notes for any configuration contract change.
- Preserve anonymization in public-facing examples and docs.
- For persona/skill changes, include concrete before/after examples and rationale.

## Skill Contributions

Domain experts are encouraged to contribute role-specific skills:

- nutrition/fitness experts for Wellness Advisor,
- professional investors for Investment Officer,
- CPAs/bookkeepers for Household Comptroller,
- estate/legal practitioners for Estate Counsel.

Start with:
- `docs/community/skill-contribution-guide.md`
