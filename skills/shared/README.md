# Shared Skill References

`skills/shared/` contains reusable reference material consumed by multiple persona skills.

## Why this folder exists

Many workflows need common conventions (taxonomy, formatting, quality checks). Centralizing shared references avoids duplicated logic and inconsistent outputs.

## Typical contents

- shared vocabulary/taxonomy,
- formatting templates,
- provenance/reporting conventions,
- reusable validation rules.

## Contribution guidance

When adding shared material:

1. ensure it applies to multiple skills,
2. keep language persona-neutral,
3. document intended consumers,
4. avoid embedding secrets or personal identifiers.

For domain-specific contribution patterns, use:
- `docs/community/skill-contribution-guide.md`
