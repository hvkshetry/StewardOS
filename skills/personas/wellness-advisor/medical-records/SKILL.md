---
name: medical-records
description: |
  Medical and genomics records management via health-graph-mcp.
  Use when: (1) Ingesting genome/lab/coverage artifacts, (2) querying PGx profile,
  (3) evaluating coverage for procedures/devices, (4) linking documents and evidence.
---

# Medical Records

## Tool Mapping (health-graph-mcp)

| Task | Tool |
|------|------|
| Create/list subject | `upsert_subject`, `list_subjects`, `link_subject_identifier` |
| Ingest genome raw data | `ingest_genome_artifact` |
| Query variant/genotype calls | `query_genotype_calls` |
| Load PharmCAT outputs | `run_pgx_pipeline` |
| Get PGx profile | `get_pgx_profile`, `list_pgx_recommendations` |
| Ingest curated assertions | `ingest_clinical_assertions`, `query_variant_assertions` |
| Ingest/query associations | `ingest_trait_associations`, `get_polygenic_context` |
| Ingest labs/admin FHIR data | `ingest_fhir_bundle`, `query_labs`, `get_lab_trends` |
| Coverage codification/check | `ingest_coverage_artifacts`, `evaluate_coverage`, `explain_coverage_determination` |
| Paperless document sync/linkage | `sync_paperless_medical_metadata`, `get_document_linkage` |
| Literature evidence graph | `add_literature_evidence`, `query_evidence_graph` |
| Policy-gated recommendation view | `get_wellness_recommendations` |
| Source freshness and refresh | `health_graph_status`, `refresh_source` |

## Drug Reference (medical-mcp)

| Task | Tool |
|------|------|
| Search FDA drug database | `medical.search_drugs` |
| Drug details by NDC code | `medical.get_drug_details` |
| Clinical practice guidelines | `medical.get_clinical_guidelines` |
| PubMed literature search | `medical.search_medical_literature` |
| Pediatric drug info | `medical.search_pediatric_drugs` |

Use drug reference tools when:
- PGx profile recommends dosage adjustment — look up standard dosing via `medical.search_drugs`
- Clinical assertion references a guideline — pull the guideline via `medical.get_clinical_guidelines`
- Subject asks about a medication — search PubMed for recent evidence

## Evidence Policy

- Tier 1 (`actionable_with_guardrails`): guideline-backed PGx.
- Tier 2 (`review_required`): clinically curated assertions.
- Tier 3 (`context_only`): GWAS/PGS context.
- Tier 4 (`research_only`): exploratory evidence only.

Nutrigenomics and exercise genomics remain `research_only`.

## Source-of-Truth Policy

- `health-graph` is authoritative for genome/clinical context, recommendation availability, and evidence tiers.
- `paperless` is a document-source/provenance bridge only; use linked metadata (`paperless_doc_id`) for traceability.
- Do not treat Paperless search results (or lack of results) as a signal that genomic/clinical data is absent.

## Reporting Quality Rules

- For weekly/persona communications, do not stop at tier counts.
- Explain each Tier 1-Tier 4 finding in plain language with:
  - recommendation target (gene-drug or variant-trait),
  - why it applies to the subject (genotype/phenotype metadata),
  - when it matters (decision trigger),
  - and tier-appropriate next-step framing.
- Every genome-informed explanation must answer "so what?" for the subject:
  - Start with the plain-English takeaway, not the genotype label
  - Say whether anything needs to happen now; if not, say that explicitly
  - Say what future decision this could affect, if any
  - Translate technical terms immediately; do not leave star alleles, rsids, or metabolizer labels unexplained
  - For Tier 3 and Tier 4 items, state clearly that they are watchlist or research context and should not drive treatment or behavior changes on their own
- Tier framing in reports:
  - Tier 1: actionable with guardrails.
  - Tier 2: review required before action.
  - Tier 3: context-only, non-deterministic.
  - Tier 4: research-only hypothesis.
- De-duplicate overlapping recommendations by gene+drug so reports are concise and non-redundant.

## Document Bridge

- Keep Paperless as OCR/document source of record.
- Persist only linked metadata and assertions in health graph.
- Use `paperless_doc_id` for provenance across records.
