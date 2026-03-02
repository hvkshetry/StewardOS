---
name: entity-compliance
description: |
  Track entity compliance: annual filing deadlines, K-1 distribution tracking,
  registration renewals, and per-entity/per-jurisdiction requirements. Use for
  compliance audits, filing season preparation, or deadline tracking.
---

# Entity Compliance

## Compliance Calendar by Entity Type

### US Entities

| Entity Type | Filing | Due Date | Frequency |
|------------|--------|----------|-----------|
| LLC (multi-member) | Form 1065 + K-1s | Mar 15 | Annual |
| LLC (single-member) | Schedule C (1040) | Apr 15 | Annual |
| S-Corp | Form 1120-S + K-1s | Mar 15 | Annual |
| C-Corp | Form 1120 | Apr 15 | Annual |
| Revocable Trust | Grantor's 1040 | Apr 15 | Annual |
| Irrevocable Trust | Form 1041 + K-1s | Apr 15 | Annual |
| All entities | State annual report | Varies by state | Annual |
| All entities | Registered agent renewal | Varies | Annual |
| All entities | Franchise tax | Varies by state | Annual |

### India Entities

| Entity Type | Filing | Due Date | Frequency |
|------------|--------|----------|-----------|
| HUF | ITR-2 or ITR-3 | Jul 31 | Annual |
| Private Ltd | ITR-6 + audit | Sep 30 | Annual |
| Private Ltd | Annual return (MCA) | Nov 30 | Annual |
| LLP | ITR-5 + Form 8 | Sep 30 | Annual |
| LLP | Form 11 (MCA) | May 30 | Annual |
| Private Trust | ITR-5 or ITR-7 | Jul 31 | Annual |
| All entities | GST returns | 20th monthly | Monthly |
| All entities | TDS returns | Quarterly | Quarterly |

## Compliance Check Workflow

### Step 1: List Active Entities

`list_entities(status='active')` — all entities requiring compliance attention.

### Step 2: Check Critical Dates

`get_upcoming_dates(days=90)` — filter for `tax_filing`, `registration_renewal` types.
Flag any overdue (due_date < today, completed = false).

### Step 3: Per-Entity Audit

For each active entity, verify:
1. **Annual filing**: Is the tax return filed or on extension?
2. **K-1s distributed**: (For pass-through entities) Are K-1s sent to all owners?
3. **State filings**: Annual report filed? Franchise tax paid?
4. **Registered agent**: Current and renewed?
5. **Documents**: Is the operating agreement / trust document linked in estate-graph?

### Step 4: Output

```
## Compliance Status — [Date]

### Overdue
| Entity | Filing | Due Date | Days Overdue |
|--------|--------|----------|-------------|

### Upcoming (Next 90 Days)
| Entity | Filing | Due Date | Days Until | Status |
|--------|--------|----------|-----------|--------|

### K-1 Distribution Status
| Entity | K-1 Recipients | Distributed? | Date |
|--------|---------------|-------------|------|

### Registration Status
| Entity | State | Agent | Renewal Due |
|--------|-------|-------|-------------|

### Gaps
[Entities missing critical dates entries, documents, or agent info]
```

## K-1 Tracking

For each pass-through entity (LLC, S-Corp, Irrevocable Trust):
1. Identify all owners from ownership_paths
2. Each owner receives a K-1 showing their share of income/loss
3. Track: K-1 prepared → K-1 sent → K-1 filed with owner's return
4. Deadline: K-1s must be sent by Mar 15 (US) to owners

## State-Specific Notes

### Delaware
- Annual franchise tax: due Mar 1 (corps) or Jun 1 (LLCs)
- Annual report: filed with franchise tax
- Registered agent: mandatory, renewal varies by provider

### California
- LLC annual fee: $800 minimum franchise tax (due Apr 15)
- LLC fee: additional fee based on total income ($0-$900+)
- Statement of Information: due within 90 days of formation, then biennially

### Texas
- Franchise tax: due May 15
- No income tax, but margin tax applies to entities with revenue > $2.47M

### India (Karnataka)
- Professional tax: applies to employed individuals and businesses
- Shops & Commercial Establishments Act: registration required
