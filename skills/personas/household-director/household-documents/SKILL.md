---
name: household-documents
description: |
  Household document filing via Paperless-ngx. Focused on receipts, warranties,
  contracts, home maintenance records, and vehicle documents. Use when filing
  household-related documents or searching for warranties, service records, etc.
---

# Household Documents

## Scope

This skill handles household-specific document filing — a subset of the full
document-management taxonomy focused on:
- Purchase receipts and invoices
- Product warranties and manuals
- Home maintenance and repair records
- Vehicle documents (registration, insurance, service)
- Utility bills and statements
- Contracts (rental, service agreements, subscriptions)

## Tool Mapping

| Task | Tool |
|------|------|
| Search documents | `search_documents` |
| Upload new document | `post_document` |
| Bulk tag/edit | `bulk_edit_documents` |
| List tags | `list_tags` |
| Create tag | `create_tag` |
| List correspondents | `list_correspondents` |
| Create correspondent | `create_correspondent` |

## Filing Workflow

For each new household document:

1. **Upload** via `post_document`
2. **Title** using conventions:
   - Receipts: `YYYY-MM-DD Receipt - [Vendor] - [Amount]`
   - Warranties: `Warranty - [Product] - Expires YYYY-MM`
   - Service records: `YYYY-MM-DD [Service Type] - [Provider]`
   - Contracts: `[Type] Agreement - [Party] - YYYY`
3. **Tags**: Apply primary (`home`, `vehicle`, `receipts`) + secondary (`warranty-active`, `tax-relevant`)
4. **Correspondent**: The vendor, provider, or service company
5. **Document type**: Receipt, Policy, Agreement, Letter, etc.

## Warranty Tracking

- Tag all warranty documents with `warranty-active`
- Include warranty expiry in the title: `Warranty - Samsung TV 65" - Expires 2028-02`
- Cross-reference with Homebox inventory items
- Monthly: check `warranty-active` documents for approaching expiry
- When expired: replace `warranty-active` with `expired`

## Vehicle Documents

- Registration renewals: tag `vehicle` + `needs-renewal`
- Insurance policies: tag `vehicle` + `insurance` + `active-policy`
- Service records: tag `vehicle`, set correspondent to service shop
- Keep all vehicle documents for duration of ownership + 3 years

## Search Strategies

| Need | Search |
|------|--------|
| Product warranty | Search by product name or vendor + tag `warranty-active` |
| Service history | Filter by correspondent (service provider) + tag `home` or `vehicle` |
| Active contracts | Filter by document type "Agreement" + tag `home` |
| Tax-deductible home expenses | Tag `home` + `tax-relevant` + date range |

## Response Parsing Note

Some Paperless MCP tools may return JSON as text content blocks. Parse the JSON payload before extracting IDs (`id`, `results[*].id`, etc.) for follow-up calls like `bulk_edit_documents` or `delete_tag`.
