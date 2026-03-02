---
name: medical-records
description: |
  Medical document management via health-records-mcp (Paperless-ngx wrapper).
  Use when: (1) Uploading medical documents, (2) Searching for lab results or
  prescriptions, (3) Managing provider information, (4) Preparing for medical
  appointments.
---

# Medical Records

## Tool Mapping (health-records-mcp)

| Task | Tool |
|------|------|
| Search medical docs | `search_medical_documents` |
| Get document content | `get_document_content` |
| Recent lab results | `get_recent_lab_results` (configurable days) |
| Insurance docs | `list_insurance_documents` |
| Upload new doc | `upload_medical_document` |
| Update tags | `update_document_tags` |
| List providers | `list_providers` |
| Docs by provider | `get_documents_by_provider` |
| Document types | `list_document_types` |
| AI suggestions | `get_document_suggestions` |
| Prescriptions | `list_prescriptions` |

## Document Upload Workflow

For each new medical document:
1. **Upload** via `upload_medical_document`
2. **Title**: `YYYY-MM-DD [Type] - [Provider/Doctor]`
   - Example: `2026-02-15 Blood Panel Results - Quest Diagnostics`
3. **Tags**: Auto-applied medical tags + additional:
   - `lab-results`, `prescription`, `referral`, `insurance`, `medical`
   - Add `child-[name]` for children's records
4. **Correspondent**: Hospital, lab, or doctor name
5. **Date**: Date on the document (not upload date)

## Appointment Preparation

When preparing for a doctor visit:
1. `get_documents_by_provider` — pull history with this provider
2. `get_recent_lab_results` — last 90 days of lab work
3. `list_prescriptions` — current medications
4. Compile a one-page summary:
   - Reason for visit
   - Current medications
   - Recent lab results (key values)
   - Questions to ask
   - Previous visit summary

## Lab Result Tracking

For ongoing health monitoring:
- Pull lab results periodically
- Track key markers over time (if multiple results):
  - CBC: hemoglobin, WBC, platelets
  - Metabolic: glucose, A1C, cholesterol (total, LDL, HDL, triglycerides)
  - Thyroid: TSH, T3, T4
  - Vitamin: D, B12, iron/ferritin
- Flag values outside normal ranges
- Note trends (improving, worsening, stable)

## Insurance Document Management

- `list_insurance_documents` for current policies
- Track policy numbers, coverage dates, in-network providers
- Before any procedure: verify insurance coverage and pre-auth requirements

## Privacy & Sensitivity

- Medical records are highly sensitive — never share without explicit instruction
- Do not store medical data outside of Paperless-ngx
- When discussing lab results, present data objectively without diagnosis
- Recommend doctor consultation for any concerning trends
