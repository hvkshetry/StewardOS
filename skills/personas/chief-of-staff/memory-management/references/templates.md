# Memory System Templates

Templates for the two-tier memory system. Copy and adapt these when bootstrapping a new household memory setup.

## Working Memory (AGENTS.md)

Use tables for compactness. Target ~50-80 lines total.

```markdown
# Memory

## Me
[Name], [Role/Head of household]. [One sentence about household context.]

## People
| Who | Role |
|-----|------|
| **Nita** | Nita Patel, education consultant |
| **Jim** | Jim Davis, estate attorney |
| **Maria** | Maria Lopez, CPA/tax advisor |
→ Full list: memory/glossary.md, profiles: memory/people/

## Terms
| Term | Meaning |
|------|---------|
| 1040-ES | Quarterly estimated tax payment |
| IPS | Investment Policy Statement |
| TLH | Tax-loss harvesting |
→ Full glossary: memory/glossary.md

## Projects
| Name | What |
|------|------|
| **Maple Reno** | 123 Maple St renovation, contractor Davis & Sons |
| **Greenwood** | School enrollment application for Greenwood Academy |
→ Details: memory/projects/

## Preferences
- Weekly family brief every Sunday evening
- Paperless-first: scan and tag everything
- No financial actions without explicit confirmation
```

## Glossary (memory/glossary.md)

```markdown
# Glossary

Household shorthand, acronyms, and internal language.

## Acronyms
| Term | Meaning | Context |
|------|---------|---------|
| IPS | Investment Policy Statement | Annual review doc |
| TLH | Tax-loss harvesting | Taxable accounts only |
| 1040-ES | Quarterly estimated tax | Due Apr/Jun/Sep/Jan |

## Internal Terms
| Term | Meaning |
|------|---------|
| the reno | Maple Street renovation project |
| family brief | Sunday evening household summary |
| monthly close | End-of-month financial reconciliation |

## Nicknames → Full Names
| Nickname | Person |
|----------|--------|
| Jim | Jim Davis (estate attorney) |
| Nita | Nita Patel (education consultant) |

## Project Codenames
| Codename | Project |
|----------|---------|
| Maple Reno | 123 Maple St renovation |
| Greenwood | School enrollment at Greenwood Academy |
```

## Person Profile (memory/people/{name}.md)

```markdown
# Jim Davis

**Also known as:** Jim
**Role:** Estate Attorney
**Firm:** Davis & Associates

## Communication
- Prefers email via Google Workspace
- Responsive within 24h on weekdays
- Schedule calls via assistant (Karen)

## Context
- Handles trust and estate documents
- Reviews all entity restructuring decisions
- Annual estate review in November

## Notes
- Sends quarterly compliance checklist
```

## Project Profile (memory/projects/{name}.md)

```markdown
# Maple Street Renovation

**Codename:** Maple Reno
**Also called:** "the reno"
**Status:** Active, targeting Q3 completion

## What It Is
Full renovation of 123 Maple Street property.

## Key People
- Davis & Sons - general contractor
- Jim - handles any property deed changes
- Maria - tracks deductible improvements

## Context
$85K budget, 4-month timeline. Permits submitted January.
```

## Household Context (memory/context/household.md)

```markdown
# Household Context

## Tools & Systems
| Tool | Used for | Internal name |
|------|----------|---------------|
| Google Workspace | Email, calendar, docs | - |
| Paperless-ngx | Document management | "docs" or "paperless" |
| Actual Budget | Budget tracking | "budget" |
| Memos | Quick notes | - |

## Service Providers
| Provider | What they do | Key people |
|----------|--------------|------------|
| Davis & Associates | Estate law | Jim (lead) |
| Patel Education | School consulting | Nita |
| Lopez CPA | Tax and accounting | Maria |

## Recurring Processes
| Process | What it means |
|---------|---------------|
| Family brief | Sunday household summary |
| Monthly close | End-of-month financial reconciliation |
| Quarterly review | Investment + tax review with advisors |
```
