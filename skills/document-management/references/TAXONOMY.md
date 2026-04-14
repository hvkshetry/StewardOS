# Document Taxonomy Reference

## Tagging Taxonomy

### Primary Category Tags

Apply exactly one primary category tag per document:

| Tag | Use For |
|-----|---------|
| `financial` | Bank statements, investment statements, tax documents, pay slips |
| `medical` | Prescriptions, lab reports, discharge summaries, vaccination records |
| `legal` | Contracts, agreements, court documents, notarized documents |
| `education` | Certificates, transcripts, school communications, course materials |
| `home` | Property documents, utility bills, maintenance records, warranties |
| `vehicle` | Registration, insurance, service records, challans |
| `insurance` | All insurance policies and claims (health, life, vehicle, property) |
| `identity` | Passports, Aadhaar, PAN, driving license, voter ID |
| `employment` | Offer letters, appraisals, relieving letters, pay slips |
| `receipts` | Purchase receipts, invoices (not bills/statements) |

### Secondary Tags (Apply as Many as Relevant)

| Tag | Use For |
|-----|---------|
| `tax-relevant` | Any document needed for tax filing (80C, 80D, HRA, capital gains) |
| `active-policy` | Insurance policies currently in force |
| `expired` | Policies, contracts, IDs past their validity |
| `needs-renewal` | Documents approaching expiry (flag 30-60 days before) |
| `reimbursable` | Medical or business expenses eligible for reimbursement |
| `warranty-active` | Products still under warranty |
| `recurring` | Bills and statements that arrive regularly |
| `original-physical` | Physical original exists and is filed (note location in custom field) |
| `child-[name]` | Documents pertaining to a specific child |

### Tag Hygiene Rules

- Every document must have exactly one primary category tag
- Apply `tax-relevant` liberally — it is easier to remove than to find missing documents at tax time
- Review `needs-renewal` tagged documents monthly
- When a policy expires, replace `active-policy` with `expired` and remove `needs-renewal`

## Correspondent Management

### Correspondent Naming Conventions

- Use the official organization name, not abbreviations: "HDFC Bank" not "HDFC"
- For individuals (doctors, lawyers): "Dr. Firstname Lastname" or "Adv. Firstname Lastname"
- For government: "Income Tax Department", "RTO Hyderabad", etc.

### When to Create New Correspondents

- Only create a new correspondent when an existing one does not match
- Before creating, search existing correspondents for partial matches
- Merge duplicates when found (same entity, different name variants)

## Document Types

| Document Type | Description |
|--------------|-------------|
| Statement | Bank/credit card/investment periodic statements |
| Bill | Utility bills, service invoices |
| Policy | Insurance policies, warranty cards |
| Certificate | Educational, professional, birth/marriage certificates |
| Report | Medical reports, lab results, appraisals |
| Agreement | Contracts, rental agreements, loan agreements |
| Tax Form | Form 16, ITR acknowledgment, TDS certificates |
| ID Document | Passports, Aadhaar, PAN, licenses |
| Receipt | Purchase receipts, payment confirmations |
| Letter | Correspondence, notices, official communications |
| Prescription | Medical prescriptions |
| Claim | Insurance claims, reimbursement filings |
