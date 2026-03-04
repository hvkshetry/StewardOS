---
name: paperless-canonical-ingestion
description: |
  Canonical ingestion workflow for family-office records: discover candidate files in
  Google Drive, Gmail attachments, OneDrive, and SharePoint; deduplicate minor variants;
  choose one canonical document; and upsert into Paperless with normalized title,
  document type, correspondent, and owner-routing tags. Use when seeding Paperless,
  running periodic syncs, or cleaning duplicates across storage systems.
---

# Paperless Canonical Ingestion

## Outcome
Create and maintain a Paperless corpus that is canonical, deduplicated, and queryable by agent role.

## Source Discovery (read-only)
- Google Drive: `search_drive_files`, `list_drive_items`, `get_drive_file_download_url`
- Gmail: `search_gmail_messages`, `get_gmail_message_content`, `get_gmail_attachment_content`
- Microsoft: `office-mcp.files` with `search`, `get`, `download`
- Paperless: `search_documents`, `get_document`, `post_document`, `update_document`, `bulk_edit_documents`

## Workflow
1. Define scope and query set.
- Start from explicit folders, entities, and case names in the request.
- Expand with keyword variants (tax years, policy numbers, case IDs, entity aliases).

2. Collect candidate files.
- Pull metadata first: filename, path/link, modified date, sender/issuer, mime type.
- Download only shortlisted files needed for canonical comparison or ingest.

3. Canonicalize duplicates and near-duplicates.
- Use normalized filename stem + issuer + date + page count + first-page text similarity.
- Treat variants as duplicates when differences are forwarding wrappers, scan quality, or cosmetic edits.
- Keep one canonical file per logical document set.
- Record why non-canonical copies were skipped.

4. Rank canonical candidates (highest wins).
- `executed/signed/final` > draft.
- authority-issued original > forwarded attachment.
- complete packet > partial extract.
- machine-readable PDF > low-quality image scan (unless scan is the only executed copy).
- newest corrected version > older versions (unless chronology itself is legally important).

5. Upsert into Paperless.
- If a logical document already exists: use `update_document` for metadata normalization.
- If not present: ingest with `post_document`.
- Normalize `title`, `document_type`, `correspondent`, and tags using `references/filing-matrix.md`.

6. Apply ownership routing.
- Add owner tags so downstream task routing is deterministic.
- Use these role tags: `owner-estate`, `owner-hc`, `owner-io`, `owner-cos`, `owner-hd`, `owner-wellness`.
- Use multiple owner tags when the document has cross-functional impact.

7. Verify and report.
- Re-query by entity/case tags and spot-check duplicates.
- Return summary: `uploaded`, `updated`, `skipped_duplicate`, `needs_user_decision`.

## Canonical Baseline Seed Pack
When seeding family-office context, prioritize these categories:
- Estate core: will, irrevocable trust, POA, healthcare directives.
- Tax core: latest 3 years personal/entity returns, notices/orders, appeals, payment proofs.
- Entity core: formation docs, operating agreements, annual reports, key minutes/resolutions.
- Property core: deed/title, mortgage/loan docs, insurance declarations, major service contracts.
- Risk core: active policies, material liabilities, active litigation/case packets.

## Guardrails
- Do not perform Microsoft write operations.
- Do not delete source files from Drive/OneDrive/SharePoint/Gmail.
- Do not ingest both canonical and clearly duplicate variants.
- Prefer `update_document` over re-upload when Paperless already has the canonical file.

## Completion Checklist
- Canonical selected for each logical document set.
- Paperless metadata normalized (`title`, `document_type`, `correspondent`, tags).
- Owner-routing tags applied for all seeded records.
- Duplicate decisions documented in the final summary.
- Ambiguities surfaced explicitly for user decision.

## References
- Filing and owner-routing matrix: `references/filing-matrix.md`
