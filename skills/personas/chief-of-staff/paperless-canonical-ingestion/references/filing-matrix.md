# Filing Matrix

Use this matrix to normalize metadata during canonical ingestion.

## Runtime ID Resolution
Always resolve IDs at runtime before update/upload:
- `list_tags` for tag IDs
- `list_document_types` for type IDs
- `list_correspondents` for correspondent IDs

Do not hardcode IDs across environments.

## Title Patterns
- Tax return: `TY YYYY Tax Return - [Entity or Person] ([Status])`
- Tax notice/order: `India Tax Case - [Authority Doc Name] - AY [Year]`
- Legal filing: `[Case/Entity] - [Document Name] ([Executed|Draft|Final])`
- Governance: `[Entity] - [Formation|Operating Agreement|Minutes|Annual Report]`
- Banking: `[Entity/Household] [Bank] Statement - YYYY-MM`
- Insurance: `[Entity/Household] [Policy Type] - [Carrier] - [Term]`
- Property: `[Property] - [Deed|Title|Mortgage|Insurance] - [Date or Term]`

## Domain Tagging
Apply one or more domain tags as applicable.
- `india-tax-case`
- `circle-h2o`
- `309-springs-road`
- `trust-irrevocable`
- `will-estate`
- `household-finance`

If a required domain tag does not exist, create it before filing.

## Owner Routing
Use owner tags to route work to the right agents.
- Estate/legal authority docs: `owner-estate`
- Tax, accounting, treasury, insurance ops: `owner-hc`
- Investment/entity/portfolio context: `owner-io`
- Admin/coordination records: `owner-cos`
- Education docs: `owner-hd`
- Medical/wellness docs: `owner-wellness`

Cross-functional documents should carry multiple owner tags.

## Document Type Mapping
Map to the closest existing Paperless document type:
- Tax Return
- Tax Notice/Order
- Legal Filing
- Corporate Governance
- Bank Statement
- Insurance Policy/Quote
- Property Record
- Correspondence

If no close type exists, create a new type and reuse it consistently.

## Canonical Decision Rules
When multiple versions exist, select in this order:
1. Signed/executed/final version
2. Issuer-original over forwarded attachment
3. Complete packet over partial packet
4. Better OCR/readability over lower-quality scan
5. Most recent corrected version

Mark all other versions as skipped duplicates in the run summary.

## Minimum Provenance to Return
For each ingested canonical document, capture:
- Source system (`gdrive`, `gmail`, `onedrive`, `sharepoint`)
- Source locator (URL, message ID + attachment ID, or drive item ID)
- Canonical reason (why this version won)
- Paperless document ID after upsert
