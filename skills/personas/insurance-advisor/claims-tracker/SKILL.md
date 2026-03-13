# Claims Tracker

## Purpose
Track active and historical insurance claims with status, documentation requirements, and follow-up actions.

## Workflow
1. Query Paperless for documents tagged `claim-submitted`, `claim-approved`, or `claim-denied`
2. For each active claim: extract claim number, carrier, date of loss, amount claimed, current status, adjuster contact
3. Check for missing documentation (e.g., police reports, repair estimates, medical records)
4. Generate timeline of claim events and next required actions
5. Summarize historical claims for loss history context

## Output Format
Active claims table + historical summary + action items list

## Tool Dependencies
- `paperless.search_documents` — claim documents
- `paperless.get_document` — claim details and attachments
