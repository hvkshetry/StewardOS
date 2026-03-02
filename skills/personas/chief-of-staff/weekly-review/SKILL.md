---
name: weekly-review
description: Weekly admin review — open tasks, upcoming deadlines, document expiry, inventory alerts, budget status.
user-invocable: true
---

# /weekly-review — Weekly Admin Review

Comprehensive weekly review of all administrative domains.

## Steps

### 1. Task Review

- Read TASKS.md
- Summarize: how many active, how many completed this week, how many waiting
- Flag stale items (waiting > 7 days, active > 14 days)
- Suggest items to move to Someday or archive

### 2. Document Expiry Review

- Paperless: search `needs-renewal` — list all with expiry dates
- Paperless: search `active-policy` — any expiring in next 60 days
- Action items: renewals to initiate, documents to update

### 3. Household Inventory

- Homebox: `list_all_maintenance` — overdue or upcoming maintenance
- Homebox: warranties expiring in next 90 days
- Homebox: any recently added items missing warranty info

### 4. Budget Status

- Actual Budget: current month spending vs budget by top categories
- Flag categories over budget
- Compare to prior month (spending trend)

### 5. Upcoming Deadlines

- Google Calendar: events in the next 2 weeks
- Paperless: document deadlines (renewal dates, filing dates)
- Any commitments from TASKS.md with due dates

### 6. Memo Digest

- Memos: any memos created this week — quick summary
- Flag any memos that need follow-up action

### 7. Compile Report

```
## Weekly Review — Week of [Date]

### Tasks
- Active: X | Completed this week: Y | Waiting: Z
- Stale items: [list]

### Documents Needing Attention
| Document | Expiry | Action Needed |
|----------|--------|---------------|

### Household
- Overdue maintenance: [list]
- Warranty alerts: [list]

### Budget
| Category | Budget | Actual | Status |
|----------|--------|--------|--------|

### Next 2 Weeks
| Date | Event/Deadline |
|------|---------------|

### Action Items for This Week
1. [ ] ...
2. [ ] ...
```
