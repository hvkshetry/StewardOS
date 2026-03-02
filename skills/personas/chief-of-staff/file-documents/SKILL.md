---
name: file-documents
description: Batch-file incoming documents with proper tags, correspondents, types, and titles.
user-invocable: true
---

# /file-documents — Batch Document Filing

Process and file all recently uploaded or untagged documents in Paperless-ngx.

## Steps

### 1. Find Unfiled Documents

- Search Paperless for recently added documents (last 7 days)
- Filter to those missing tags, correspondents, or proper titles
- Present the list: document ID, current title, added date

### 2. Review Each Document

For each unfiled document:
1. Read the document content/OCR text
2. Determine document type (bill, statement, receipt, contract, medical, etc.)
3. Apply the filing rules from the `document-filing` skill:
   - Set proper title using naming conventions
   - Assign primary category tag
   - Add secondary tags (tax-relevant, active-policy, etc.)
   - Set correspondent
   - Set document type
   - Correct the document date if needed

### 3. Present Filing Plan

Before applying, show the user the proposed metadata for each document:

```
| # | Current Title | Proposed Title | Tags | Correspondent | Type |
|---|--------------|---------------|------|---------------|------|
| 1 | scan_001.pdf | 2026-02 Electricity Bill - PG&E | financial, recurring | PG&E | Bill |
| 2 | IMG_2341.jpg | 2026-02-20 Receipt - Costco - $156 | receipts | Costco | Receipt |
```

### 4. Apply After Approval

Use `bulk_edit_documents` to apply tags and metadata in batch.
Confirm completion with count of documents filed.
