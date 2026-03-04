---
name: memory-management
description: Two-tier memory system that makes Codex CLI a true household collaborator. Decodes shorthand, acronyms, nicknames, and internal language so Codex understands requests like a family office staff member would. AGENTS.md for working memory, memory/ directory for the full knowledge base.
---

# Memory Management

Memory makes Codex your household collaborator - someone who speaks your family's internal language.

## The Goal

Transform shorthand into understanding:

```
User: "check on the reno permits for maple"
              ↓ Codex decodes
"Check on building permits for the Maple Street property renovation
 (123 Maple St, contractor: Davis & Sons, target completion Q3)"
```

Without memory, that request is meaningless. With memory, Codex knows:
- **reno** → the renovation project
- **maple** → 123 Maple Street property
- **permits** → building permits submitted in January

## Architecture

```
AGENTS.md          ← Hot cache (~30 people/entities, common terms)
memory/
  glossary.md      ← Full decoder ring (everything)
  people/          ← Complete profiles
  projects/        ← Project details
  context/         ← Household, services, tools
```

**AGENTS.md (Hot Cache):**
- Top ~30 people you interact with most (family, advisors, vendors, service providers)
- ~30 most common acronyms/terms
- Active projects (5-15)
- Your preferences
- **Goal: Cover 90% of daily decoding needs**

**memory/glossary.md (Full Glossary):**
- Complete decoder ring - everyone, every term
- Searched when something isn't in AGENTS.md
- Can grow indefinitely

**memory/people/, projects/, context/:**
- Rich detail when needed for execution
- Full profiles, history, context

## Lookup Flow

```
User: "ask nita about the enrollment for greenwood"

1. Check AGENTS.md (hot cache)
   → Nita? ✓ Nita Patel, education consultant
   → enrollment? ✓ School enrollment process
   → Greenwood? ✓ Greenwood Academy application

2. If not found → search memory/glossary.md
   → Full glossary has everyone/everything

3. If still not found → ask user
   → "What does X mean? I'll remember it."
```

This tiered approach keeps AGENTS.md lean (~100 lines) while supporting unlimited scale in memory/.

## File Locations

- **Working memory:** `AGENTS.md` in current working directory
- **Deep memory:** `memory/` subdirectory

## Memory Format Templates

Use tables for compactness in AGENTS.md. Target ~50-80 lines for the hot cache.

For full templates with examples for each file type (AGENTS.md, glossary.md, people profiles, project profiles, household context), see [references/templates.md](references/templates.md).

Key file structure:
- **AGENTS.md**: Sections for Me, People (table), Terms (table), Projects (table), Preferences (bullets)
- **memory/glossary.md**: Acronyms, internal terms, nicknames, project codenames — all as tables
- **memory/people/{name}.md**: Also-known-as, role, communication prefs, context, notes
- **memory/projects/{name}.md**: Codename, status, description, key people, context
- **memory/context/household.md**: Tools/systems, service providers, recurring processes

## How to Interact

### Decoding User Input (Tiered Lookup)

**Always** decode shorthand before acting on requests:

```
1. AGENTS.md (hot cache)     → Check first, covers 90% of cases
2. memory/glossary.md        → Full glossary if not in hot cache
3. memory/people/, projects/ → Rich detail when needed
4. Ask user                  → Unknown term? Learn it.
```

Example:
```
User: "ask jim about the trust amendment for maple"

AGENTS.md lookup:
  "jim" → Jim Davis, estate attorney ✓
  "trust amendment" → (not in hot cache)
  "maple" → Maple Street property ✓

memory/glossary.md lookup:
  "trust amendment" → property trust restructuring doc ✓

Now Codex can act with full context.
```

### Adding Memory

When user says "remember this" or "X means Y":

1. **Glossary items** (acronyms, terms, shorthand):
   - Add to memory/glossary.md
   - If frequently used, add to AGENTS.md Quick Glossary

2. **People:**
   - Create/update memory/people/{name}.md
   - Add to AGENTS.md Key People if important
   - **Capture nicknames** - critical for decoding

3. **Projects:**
   - Create/update memory/projects/{name}.md
   - Add to AGENTS.md Active Projects if current
   - **Capture codenames** - "maple reno", "greenwood", etc.

4. **Preferences:** Add to AGENTS.md Preferences section

### Recalling Memory

When user asks "who is X" or "what does X mean":

1. Check AGENTS.md first
2. Check memory/ for full detail
3. If not found: "I don't know what X means yet. Can you tell me?"

### Progressive Disclosure

1. Load AGENTS.md for quick parsing of any request
2. Dive into memory/ when you need full context for execution
3. Example: drafting an email to jim about the trust amendment
   - AGENTS.md tells you Jim = Jim Davis, estate attorney
   - memory/people/jim-davis.md tells you he prefers email, is responsive within 24h

## Conventions

- **Bold** terms in AGENTS.md for scannability
- Keep AGENTS.md under ~100 lines (the "hot 30" rule)
- Filenames: lowercase, hyphens (`jim-davis.md`, `maple-renovation.md`)
- Always capture nicknames and alternate names
- Glossary tables for easy lookup
- When something's used frequently, promote it to AGENTS.md
- When something goes stale, demote it to memory/ only

## What Goes Where

| Type | AGENTS.md (Hot Cache) | memory/ (Full Storage) |
|------|----------------------|------------------------|
| Person | Top ~30 frequent contacts | glossary.md + people/{name}.md |
| Acronym/term | ~30 most common | glossary.md (complete list) |
| Project | Active projects only | glossary.md + projects/{name}.md |
| Nickname | In Key People if top 30 | glossary.md (all nicknames) |
| Household context | Quick reference only | context/household.md |
| Preferences | All preferences | - |
| Historical/stale | ✗ Remove | ✓ Keep in memory/ |

## Promotion / Demotion

**Promote to AGENTS.md when:**
- You use a term/person frequently
- It's part of active work

**Demote to memory/ only when:**
- Project completed
- Person no longer frequent contact
- Term rarely used

This keeps AGENTS.md fresh and relevant.
