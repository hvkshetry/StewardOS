---
name: tax-doc-scan
description: |
  Visual inspection and classification of tax documents. Scans every page
  (never trust filenames), classifies by IRS form type, files to Paperless.
  Use when tax documents arrive via Gmail or Drive and need to be discovered,
  classified, and filed, or when checking completeness of tax document collection.
user-invocable: true
---

# /tax-doc-scan — Tax Document Visual Inspection & Classification

Scan, visually inspect, and classify every tax document across Gmail, Drive, and Paperless.
The cardinal rule: **never trust filenames** — every page must be visually inspected and classified
from its actual content.

## MCP Tool Map

| Task | Tool | Notes |
|------|------|-------|
| Search Gmail for tax attachments | `google-workspace-personal-ro.search_gmail_messages` | Date-range + keyword queries |
| Search Drive for tax folders | `google-workspace-personal-ro.search_drive_files` | Folder and filename scans |
| Download Drive file | `google-workspace-personal-ro.get_drive_file_content` | Retrieve for visual inspection |
| Search Paperless documents | `paperless.search_documents` | Find untagged or recently added docs |
| Get Paperless document | `paperless.get_document` | Metadata and content retrieval |
| Download Paperless document | `paperless.download_document` | Full document for page-level inspection |
| Upload to Paperless | `paperless.post_document` | Ingest with metadata |
| Update Paperless metadata | `paperless.update_document` | Correct tags, title, correspondent |
| List Paperless tags | `paperless.list_tags` | Resolve tag IDs at runtime |

## Workflow

### Phase 1: Discovery

Scan all document sources for tax-season candidates.

1. **Gmail** — search for tax-season attachments:
   - Query: `W-2 OR 1099 OR K-1 OR 1098 OR 1095 OR 5498 OR "tax document" OR "tax form"` scoped to the relevant date range (typically Jan 1 through Apr 15 of the filing year).
   - Extract: sender, subject, date, attachment filenames.

2. **Drive** — search for tax folders and loose documents:
   - Look in known tax folders (e.g., `Tax/TY 2025/`) and run keyword queries.
   - Extract: filename, path, modified date, sharing status.

3. **Paperless** — search for recently added untagged documents:
   - Filter to documents added in the last 90 days without a `tax-relevant` tag or without any tags at all.
   - Check for documents that may have been auto-ingested but not classified.

4. **Build candidate list** with columns: source (Gmail/Drive/Paperless), filename, date received/modified, sender or folder path, preliminary guess from filename.

### Phase 2: Visual Inspection

For every candidate document — no exceptions:

1. Download or retrieve the full document content.
2. Inspect **every page** of every document. Multi-page PDFs may contain multiple distinct forms, cover letters, or state vs federal copies.
3. Identify the actual document type from content (form headers, OMB numbers, payer/employer blocks, tax year, recipient name). See `references/tax-doc-types.md` for visual identification hints per form type.

### Phase 3: Classification

Classify each inspected document using `references/tax-doc-types.md`.

For each document, extract:
- **Document type**: W-2, 1099-INT, 1099-DIV, K-1, 1098, etc.
- **Tax year**: as printed on the form.
- **Payer/employer**: name and EIN.
- **Recipient**: name and SSN last 4 only (never log or store full SSN/TIN).
- **Key amounts**: gross wages, interest income, dividends, capital gains, etc. — the primary box values.

Flag discrepancies:
- Filename says "1099" but content is actually a W-2.
- Email subject says "2024 Tax Documents" but form shows TY 2025.
- Recipient name does not match any household member.
- Same form appears in multiple sources (Gmail attachment + Drive copy).

### Phase 4: Filing

File each classified document to Paperless following the conventions in `references/tax-doc-types.md` (Filing Conventions section) and the `document-filing` skill taxonomy.

1. Apply title format, tags, correspondent, and document type per the reference file conventions.
2. Set tax year custom field if the Paperless instance supports it.
3. **Deduplication** — before uploading, search Paperless for existing copies (match on form type + payer + tax year). If a match exists, update metadata rather than re-uploading.

### Phase 5: Completeness Report

Generate a filing-season completeness checklist.

1. **Expected documents** — based on prior year sources:
   - List every employer, bank, brokerage, partnership, and institution that issued a tax document last year.
   - For each, note the expected form type(s).

2. **Received vs expected**:

   ```
   | Source | Form | TY | Status | Paperless ID |
   |--------|------|----|--------|--------------|
   | Acme Corp | W-2 | 2025 | Received | #1234 |
   | Chase Bank | 1099-INT | 2025 | Received | #1235 |
   | Fidelity | 1099-DIV | 2025 | MISSING | — |
   ```

3. **Flag gaps**: "Missing 1099-DIV from Fidelity (received last year on 2025-02-12)."

4. **Flag duplicates**: same form type from same source found in multiple locations.

5. **Recommended follow-up**: contact payer, check online portal, wait for late mailing.

## Output Contract

Every run must return:

| Field | Type | Description |
|-------|------|-------------|
| `as_of` | ISO 8601 timestamp | When the scan was performed |
| `documents_scanned` | integer | Total candidate documents inspected |
| `classification_results` | list | Each entry: `{source, filename, classified_type, tax_year, payer, recipient_last4, key_amounts, paperless_doc_id}` |
| `discrepancies` | list | Filename-vs-content mismatches, year mismatches, unknown recipients |
| `completeness_checklist` | list | Expected vs received per source and form type |
| `filing_results` | list | Paperless upload/update confirmations with document IDs |
| `gaps` | list | Missing documents with prior-year context |
| `recommended_actions` | list | Follow-up steps for gaps and discrepancies |

## Critical Rules

1. **Never trust filenames** — always inspect the actual document content. A file named `1099.pdf` might contain a W-2, a cover letter, or a completely unrelated document.
2. **Every page matters** — multi-page PDFs may contain multiple distinct forms. Inspect each page individually and classify separately if needed.
3. **Privacy** — only log the last 4 digits of SSN/TIN. Never store, display, or transmit full Social Security Numbers or Taxpayer Identification Numbers.
4. **Provenance** — track and report the source system (Gmail, Drive, or Paperless) and source locator (message ID, file ID, document ID) for every document.
5. **Idempotency** — re-running the scan should not create duplicate Paperless entries. Always check for existing documents before uploading.
6. **Tax year accuracy** — use the tax year printed on the form, not the date the email was received or the file was modified.

## References

- Tax document classification matrix: `references/tax-doc-types.md`
- Filing taxonomy and title conventions: `../document-filing/SKILL.md`
- Canonical ingestion workflow: `../paperless-canonical-ingestion/SKILL.md`
