---
name: compliance-check
description: Entity compliance audit — overdue filings, expiring registrations, K-1 status, and state-specific requirements.
user-invocable: true
---

# /compliance-check — Entity Compliance Audit

Check compliance status for all active entities using the `entity-compliance` skill workflow.

## Steps

Follow the `entity-compliance` skill in full:

1. **Active Entities**: `list_entities(status='active')` — all entities needing compliance
2. **Critical Dates**: `get_upcoming_dates(days=90)` — filter for filing and renewal types
3. **Overdue Items**: Flag any critical dates where due_date < today and not completed
4. **Per-Entity Audit**: For each entity, check:
   - Annual tax filing status
   - K-1 distribution status (pass-through entities)
   - State annual report / franchise tax
   - Registered agent renewal
   - Operating agreement / trust document linked
5. **State-Specific**: Apply the state-specific rules from the `entity-compliance` skill

## Routing Guardrails

- Use `estate-planning` for legal-entity status, dates, and document linkage
- Use `household-tax` for filing-readiness and estimated-payment context
- Use `finance-graph` only when valuation/statement context materially affects compliance risk

## Output Contract

- Include three sections in this order: `Overdue`, `Next 30 days`, `31-90 days`
- For each flagged item, include: due date, responsible entity/person, and required evidence document
- Add a short provenance line listing which MCPs were queried

Present the compliance report in the format defined in the `entity-compliance` skill.
Prioritize: overdue items first, then upcoming 30 days, then 30-90 days.
