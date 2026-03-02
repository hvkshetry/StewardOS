---
name: start
description: Daily briefing — triage email, review calendar, surface expiring documents, and check household alerts.
user-invocable: true
---

# /start — Daily Briefing

Run this every morning to get a consolidated view of what needs attention today.

## Steps

### 1. Email Triage (Google Workspace)

- Fetch unread emails from the last 24 hours
- Categorize each: urgent, action-required, informational, low-priority
- For urgent items: summarize and flag with recommended action
- For action-required: extract deadlines and add to task list
- Draft quick replies for routine correspondence if appropriate

### 2. Calendar Review (Google Workspace)

- Pull today's events and tomorrow's events
- Flag scheduling conflicts
- For each meeting: note time, participants, and any prep needed
- Surface free blocks for scheduling

### 3. Expiring Documents (Paperless-ngx)

- Search for documents tagged `needs-renewal` with expiry in next 30 days
- Search for documents tagged `active-policy` with expiry in next 60 days
- List any action items for renewals

### 4. Household Alerts

- Homebox: any overdue maintenance entries
- Homebox: warranties expiring in next 30 days
- Memos: any pinned/flagged memos from yesterday

### 5. Budget Quick Check (Actual Budget)

- Current month spending vs budget (summary only)
- Flag any categories already over budget

### 6. Compile Briefing

Present as a scannable daily briefing:

```
## Daily Briefing — [Date]

### Urgent
- [Items needing immediate attention]

### Today's Calendar
| Time | Event | Prep Needed |
|------|-------|-------------|

### Action Items
- [ ] [From email triage]
- [ ] [From expiring docs]

### Alerts
- [Maintenance, warranty, budget alerts]

### FYI
- [Informational items from email]
```
