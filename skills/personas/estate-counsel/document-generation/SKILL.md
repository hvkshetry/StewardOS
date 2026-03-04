---
name: document-generation
description: |
  Generate estate planning documents using python-docx and Jinja2 templates.
  Covers trust amendments, LLC agreements, powers of attorney, and other
  estate documents. Generated docs are uploaded to Paperless-ngx.
---

# Document Generation

## Approach

Use python-docx + Jinja2 templates stored in `~/personal/servers/estate-planning-mcp/templates/`.
This is more flexible than Docassemble for family office documents that require
customization per entity and jurisdiction.

## Tool Routing

- `estate-planning`: entity/person/ownership context and document linkage metadata
- `paperless`: uploaded document storage, tags, correspondents, and retrieval
- `household-tax`: only when tax-language assumptions are required for narrative sections
- `finance-graph`: only when valuation history must be cited inside a document appendix
- Do not write finance-fact payloads into estate-planning document metadata

## Template Types

| Template | Use Case | Key Variables |
|----------|----------|---------------|
| trust-amendment | Modify trust provisions | trust_name, amendment_number, changes, effective_date |
| llc-operating-agreement | New LLC formation | llc_name, members, percentages, jurisdiction, manager |
| power-of-attorney | Grant POA | principal, agent, scope, jurisdiction, effective_date |
| certificate-of-trust | Prove trust existence | trust_name, trustee, formation_date, jurisdiction |
| assignment-of-assets | Transfer assets to entity | asset_description, from_party, to_entity, date |
| beneficiary-designation | Designate beneficiaries | account, primary_beneficiary, contingent, percentages |

## Generation Workflow

### Step 1: Gather Data from Estate Graph

Query `estate-planning` for:
- Entity details: `get_entity` (name, type, jurisdiction, formation date, grantor, trustee)
- People details: `get_person` (legal name, address, tax ID)
- Ownership: `get_ownership_graph` (current ownership structure)
- Existing documents: linked docs to avoid duplication

### Step 2: Select Template

Match the document need to a template. If no template exists:
- Note the gap
- Generate the document from scratch using python-docx
- Save the new template for future use

### Step 3: Fill Template Variables

Map estate-planning data to template variables:
- Legal names (not preferred names)
- Full addresses
- Tax IDs (only when required by the document type)
- Dates in jurisdiction-appropriate format
- Entity-specific terms (e.g., "Member" for LLC, "Beneficiary" for trust)

### Step 4: Generate Document

Execute python-docx code to render the template with variables.
Apply formatting:
- Professional formatting (margins, fonts, spacing)
- Page numbers
- Signature blocks with date lines
- Notary acknowledgment blocks where required

### Step 5: Upload to Paperless-ngx

Via paperless tools:
1. Upload the generated .docx as a new document
2. Title: `[Doc Type] - [Entity Name] - YYYY-MM-DD`
3. Tags: `legal`, appropriate secondary tags
4. Correspondent: The entity or attorney
5. Link in estate-planning: `link_document` (or `upsert_document_metadata`) to associate with entity/asset

## Output Contract

Return:
- Generated document filename and template used
- Linked `paperless_doc_id`
- Linked estate object IDs (`entity_id` / `asset_id` / `person_id`)
- Open attorney-review flags (witness/notary/jurisdiction-specific checks)

## Important Constraints

- **Not legal advice**: All generated documents should be reviewed by a qualified attorney
- **Wet signatures required**: Estate docs (wills, trusts, deeds) require wet signatures and often notarization — e-sign is insufficient
- **Jurisdiction-specific**: Templates must account for jurisdiction-specific requirements (e.g., witness requirements, notary formats differ by state)
- **Version control**: Always include amendment number and effective date; never overwrite prior versions
- **Confidential**: Generated documents contain sensitive information (tax IDs, ownership, valuations)
