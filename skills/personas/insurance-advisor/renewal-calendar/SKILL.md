# Renewal Calendar

## Purpose
Track upcoming policy renewals with comparison shopping triggers, rate history, and negotiation preparation.

## Workflow
1. Query Paperless for all active policies and extract renewal/expiration dates
2. Build calendar of upcoming renewals (next 90 days, 180 days, 365 days)
3. For each upcoming renewal:
   - Pull premium history from Paperless documents
   - Calculate year-over-year rate changes
   - Flag policies with >10% rate increases for comparison shopping
   - Note any coverage changes or endorsement additions needed
4. Cross-reference with Google Calendar for any scheduled agent/broker meetings
5. Generate prioritized action list by urgency

## Output Format
Calendar view + rate trend analysis + action items sorted by renewal date

## Tool Dependencies
- `paperless.search_documents` — policy documents with dates
- `paperless.get_document` — premium history details
- `google-workspace-personal-ro.get_events` — existing broker meetings
- `actual-budget.transaction` — premium payment history
