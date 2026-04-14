---
name: document-management
description: "Personal document management skill using Paperless-ngx. Use when: (1) Ingesting and filing new documents, (2) Searching for existing documents, (3) Applying tags and correspondents, (4) Managing retention policies, (5) Integrating documents with other personal workflows (tax prep, medical records, insurance claims). Tools: paperless-mcp for all document operations."
---

# Document Management

## Tool Mapping

| Task | Tool | Notes |
|------|------|-------|
| Search documents | `search_documents` | Full-text search across all documents |
| Get document details | `get_document` | Metadata, tags, correspondent, dates |
| Upload document | `upload_document` | Ingest new document with initial metadata |
| Update document metadata | `update_document` | Add/change tags, correspondent, dates, title |
| List/manage tags | `get_tags`, `create_tag` | Taxonomy management |
| List/manage correspondents | `get_correspondents`, `create_correspondent` | Organization/person who issued the document |
| List/manage document types | `get_document_types`, `create_document_type` | Classify by type |
| Download document | `get_document_content` | Retrieve original or archived version |

## Document Intake Workflow

### Standard Intake Procedure

For every new document:

1. **Upload** the document via `upload_document`

```
upload_document(document="/path/to/file.pdf", title="2026-02 Electricity Bill - Tata Power", correspondent="Tata Power", document_type="Bill", tags=["home", "recurring"])
```

2. **Review auto-classification** — Paperless-ngx will attempt auto-tagging and correspondent matching. If auto-classification assigned the wrong correspondent or tags, correct via `update_document`:

```
update_document(id=1234, correspondent="Tata Power", tags=["home", "recurring"])
```

3. **Verify and correct metadata**:
   - Title: Clear, descriptive, includes date if relevant (e.g., "2026-02 Electricity Bill - Tata Power")
   - Date: The document's date (issue date, statement date), not the upload date
   - Correspondent: The organization or person who issued the document
   - Document type: Select from the taxonomy reference
   - Tags: Apply all relevant tags from the taxonomy reference
4. **Confirm filing** — Verify the document appears in expected searches by running `search_documents`:

```
search_documents(query="Electricity Bill Tata Power", tags=["home"])
```

### Title Conventions

Use consistent title formatting for searchability:

| Document Type | Title Format | Example |
|--------------|-------------|---------|
| Monthly bills | `YYYY-MM [Service] Bill - [Provider]` | `2026-02 Electricity Bill - Tata Power` |
| Bank statements | `YYYY-MM [Account Type] Statement - [Bank]` | `2026-02 Savings Statement - HDFC` |
| Tax forms | `FY YYYY-YY [Form Name]` | `FY 2025-26 Form 16` |
| Insurance | `[Type] Policy - [Provider] - [Policy#]` | `Health Policy - Star Health - 12345` |
| Medical | `YYYY-MM-DD [Type] - [Provider/Doctor]` | `2026-02-15 Blood Test Results - Apollo Labs` |
| Contracts | `[Type] Agreement - [Party] - YYYY` | `Rental Agreement - Landlord Name - 2026` |
| Identity docs | `[Doc Type] - [Person]` | `Passport - Principal` |
| Receipts | `YYYY-MM-DD Receipt - [Vendor] - [Amount]` | `2026-02-20 Receipt - Amazon - 4500` |

## Taxonomy Reference

Document classification uses primary category tags (exactly one per document), secondary tags (as many as relevant), correspondents, and document types. See [references/TAXONOMY.md](references/TAXONOMY.md) for the complete taxonomy tables, naming conventions, and tag hygiene rules.

## Search Strategies

### Finding Documents

| Need | Search Approach |
|------|----------------|
| Specific document | Search by title keywords + date range |
| All docs from an org | Filter by correspondent |
| Tax season gathering | Filter by tag `tax-relevant` + date range for the FY |
| Active insurance | Filter by tags `insurance` + `active-policy` |
| Medical history | Filter by tag `medical` + correspondent (doctor/hospital) |
| Expiring documents | Filter by tag `needs-renewal` |
| Recent uploads | Sort by added date, descending |

### Search Tips

1. Use full-text search for content within documents (OCR text)
2. Combine tag filters with date ranges for precise results
3. When searching for a document you know exists but cannot find, try:
   - Search by correspondent instead of title
   - Broaden the date range
   - Search for distinctive terms from within the document content
   - Check if the document was tagged with an unexpected primary category

## Retention Policies

Quarterly retention reviews ensure expired documents are archived or deleted on schedule. See [references/RETENTION.md](references/RETENTION.md) for retention periods by document type and the review procedure.

## Integration with Other Skills

### Tax Preparation

1. Search for all documents tagged `tax-relevant` within the financial year
2. Group by deduction section (80C, 80D, 24, etc.) and verify each claimed deduction has supporting documentation
3. Cross-reference against actual-mcp transaction data for amount verification

### Medical Records

1. Search prior records by correspondent (hospital/doctor) or tag `medical`; pull recent lab reports and prescriptions
2. After a visit, upload new documents with appropriate tags; for children, always apply the `child-[name]` tag

### Insurance Claims

1. Locate the active policy: filter by `insurance` + `active-policy` + correspondent
2. Gather supporting documents (medical reports for health, FIR for vehicle, etc.) and upload claim submission documents tagged as `claim`
3. Track claim status by adding notes to the claim document

## Key Reminders

1. **Ignoring document dates** — The document date is the date on the document (statement date, issue date), not when it was uploaded. Paperless uses this for date-range filtering.
2. **Not reviewing needs-renewal** — Check monthly. An expired insurance policy with no renewal is a risk, not just a filing issue.
