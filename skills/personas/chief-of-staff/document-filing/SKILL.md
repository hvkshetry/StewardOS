---
name: document-filing
description: |
  Paperless-ngx document filing skill with tagging taxonomy, retention policies,
  and batch filing workflows. Use when ingesting, tagging, searching, or managing
  documents in Paperless-ngx.
---

# Document Filing

## Tool Mapping

| Task | Tool | Notes |
|------|------|-------|
| Search documents | `search_documents` | Full-text search across all documents |
| Get document details | `get_document` | Metadata, tags, correspondent, dates |
| Upload document | `post_document` | Ingest new document with initial metadata |
| Bulk operations | `bulk_edit_documents` | Add/remove tags, set correspondent/type |
| List/manage tags | `list_tags`, `create_tag` | Taxonomy management |
| List/manage correspondents | `list_correspondents`, `create_correspondent` | Organization management |
| List/manage types | `list_document_types`, `create_document_type` | Classification |

## Fast Path For Email Attachments

When an email explicitly asks you to ingest, file, or tag attached documents, treat that as approval to file them immediately.

Use this workflow:

1. Read the email and inspect the attachments.
2. Resolve only the metadata you need with `list_tags`, `list_document_types`, and `list_correspondents`.
3. Use `search_documents` only to avoid an obvious duplicate or to reuse an existing naming pattern for the same entity or document family.
4. Upload each attachment with `post_document`.
5. Reply with what was filed, which metadata was applied, and any follow-up needed.

Avoid local config or environment discovery, MCP resource discovery, and broad archive searches unless the upload or classification is genuinely blocked.

## Title Conventions

| Document Type | Title Format | Example |
|--------------|-------------|---------|
| Monthly bills | `YYYY-MM [Service] Bill - [Provider]` | `2026-02 Electricity Bill - PG&E` |
| Bank statements | `YYYY-MM [Account Type] Statement - [Bank]` | `2026-02 Checking Statement - Chase` |
| Tax forms | `TY YYYY [Form Name]` | `TY 2025 W-2 - Employer Name` |
| Insurance | `[Type] Policy - [Provider] - [Policy#]` | `Auto Policy - GEICO - 12345` |
| Medical | `YYYY-MM-DD [Type] - [Provider]` | `2026-02-15 Lab Results - Quest` |
| Contracts | `[Type] Agreement - [Party] - YYYY` | `Lease Agreement - Property Mgmt - 2026` |
| Identity docs | `[Doc Type] - [Person]` | `Passport - Principal` |
| Receipts | `YYYY-MM-DD Receipt - [Vendor] - [Amount]` | `2026-02-20 Receipt - Amazon - $45` |

## Tagging Taxonomy

### Primary Category (exactly one per document)

| Tag | Use For |
|-----|---------|
| `financial` | Bank statements, investment statements, tax documents, pay slips |
| `medical` | Prescriptions, lab reports, discharge summaries, vaccination records |
| `legal` | Contracts, agreements, court documents, notarized documents |
| `education` | Certificates, transcripts, school communications |
| `home` | Property documents, utility bills, maintenance records, warranties |
| `vehicle` | Registration, insurance, service records |
| `insurance` | All insurance policies and claims |
| `identity` | Passports, SSN cards, driver's license |
| `employment` | Offer letters, W-2s, pay stubs |
| `receipts` | Purchase receipts, invoices |

### Secondary Tags (apply as many as relevant)

| Tag | Use For |
|-----|---------|
| `tax-relevant` | Any document needed for tax filing |
| `active-policy` | Insurance policies currently in force |
| `expired` | Past validity |
| `needs-renewal` | Approaching expiry (flag 30-60 days before) |
| `warranty-active` | Products still under warranty |
| `recurring` | Bills/statements that arrive regularly |

## Batch Filing Workflow

1. List recent untagged documents
2. For each document: set title (conventions above), primary category tag, secondary tags, correspondent, document type, date
3. Confirm filing with the user before bulk applying

For inbound email attachments that explicitly ask you to ingest or tag the attached documents, no extra confirmation is required before filing.

## Retention Policies

| Document Type | Keep For |
|--------------|----------|
| Tax returns + supporting | 7 years from filing |
| Bank/investment statements | 7 years |
| Medical records | Indefinite |
| Property documents | Indefinite |
| Identity documents | Until replaced |
| Utility bills | 1 year (unless tax-relevant) |
| General receipts | 1 year or warranty period |
| Warranties | Duration of warranty |

## Quarterly Review

1. Filter by `needs-renewal` — check approaching expirations
2. Filter by `expired` — verify retention period, archive or delete
3. Check utility bills > 1 year without `tax-relevant` — safe to delete
