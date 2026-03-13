---
name: tax-form-prep
description: |
  End-of-year IRS form preparation: document checklist, form identification,
  form completion guidance, and audit review. Use when preparing tax returns,
  filling IRS forms, assembling tax document checklists, reviewing form
  completeness, or reconciling income sources during tax season.
user-invocable: true
---

# /tax-form-prep — IRS Tax Form Preparation

Prepare IRS tax forms using source documents, exact tax computation, and cross-server baselines. This skill is fail-closed: if facts are outside the supported 2025/2026 `US` + `MA` individual/fiduciary scope, stop and explain what is unsupported. Never estimate unsupported tax computations.

## Source-of-Truth Hierarchy

**Paperless tax documents are the authoritative source for all income and deduction figures.** W-2, 1099, K-1, 1098, and other IRS information returns filed to Paperless are the primary evidence layer — form line items are populated exclusively from these documents.

Actual Budget and Ghostfolio are **secondary reconciliation sources only**. Their role is:
1. Flag discrepancies between tracked income/investment data and Paperless documents (e.g., dividends in Ghostfolio with no matching 1099-DIV).
2. Trigger searches for missing forms — if Actual Budget shows employer income but no W-2 exists in Paperless, flag the gap and search for the missing document.
3. They do NOT override or substitute for values on IRS information returns.

## MCP Tool Map

- Evidence documents (primary): `paperless.search_documents`, `paperless.get_document`, `paperless.download_document` — source W-2, 1099, K-1 (authoritative)
- Tax computation: `household-tax.assess_exact_support`, `household-tax.compute_individual_return_exact`, `household-tax.compute_fiduciary_return_exact`
- Reconciliation (secondary): `actual-budget.analytics(operation="monthly_summary")` — flag income discrepancies, trigger missing-form searches
- Reconciliation (secondary): `ghostfolio.portfolio(operation="dividends")`, `ghostfolio.portfolio(operation="summary")` — flag missing 1099-DIV/1099-B, do not use as form input

Adapted from calef/us-federal-tax-assistant-skill (GPLv3 — private use).

## Scripts

- `scripts/download_irs_forms.py` — download IRS PDF forms organized by year; reads `scripts/forms-metadata.json` for URL construction

## Form Location

IRS form PDFs are not bundled with this skill. To get local copies:

```bash
cd agent-configs/household-comptroller/scripts
python3 download_irs_forms.py 2025
```

Forms download to `./forms/<year>/`. If the user prefers manual download, direct them to [irs.gov/forms-instructions](https://www.irs.gov/forms-instructions).

## 4-Phase Workflow

### Phase 1: Document Checklist

1. Search Paperless for all tax-year source documents (W-2, 1099 variants, K-1, 1098 variants).
2. Classify each document by IRS form type. See `references/irs-form-matrix.md` for the complete classification and routing.
3. Generate a completeness checklist: expected documents vs received documents.
4. Flag missing documents with the expected source (employer, bank, brokerage, etc.).

### Phase 2: Form Identification

Based on available documents and income types, identify required IRS forms and schedules. Map each source document to the form or schedule it feeds using `references/irs-form-matrix.md` (covers primary returns, schedules, additional forms, estimated payments, and MA state forms).

### Phase 3: Form Completion Guidance

1. For each identified form, provide line-by-line data mapping **exclusively from Paperless source documents** (W-2, 1099, K-1, 1098, etc.). These are the authoritative figures.
2. Use `household-tax.compute_individual_return_exact` or `household-tax.compute_fiduciary_return_exact` for exact computation where supported (2025/2026 US+MA scope). Individual returns support structured itemized deductions and child tax credit (dependents).
3. Flag forms and schedules outside the exact support surface — do NOT estimate; stop and explain the gaps.
4. **Reconciliation pass** — compare Actual Budget income totals and Ghostfolio dividend/capital gain totals against Paperless documents. Any discrepancy triggers a search for missing forms (e.g., Ghostfolio shows dividends from Fidelity but no 1099-DIV exists → flag as missing and search Paperless). Do NOT use Actual Budget or Ghostfolio figures as form inputs.

### Phase 4: Audit Review

1. **Math verification:** Confirm arithmetic across all forms (totals, carryforwards, cross-form references).
2. **Cross-reference consistency:** Verify income on Form 1040 matches the sum of all source documents. Verify Schedule D totals match Form 8949 aggregates.
3. **Common error checklist:**
   - Missing signatures or dates
   - Wrong filing status
   - Forgotten schedules (e.g., Schedule B omitted when interest exceeds $1,500)
   - Mismatched SSN/EIN references
   - Overlooked estimated payment credits
4. **State-specific items:** Identify MA Form 1 line items that differ from the federal return (5% flat rate, Part B interest/dividends, short-term capital gains rate, no federal Schedule A passthrough).

## Output Contract

Always include:
- `as_of` timestamp
- document completeness matrix (expected vs received, by type and source)
- form/schedule list with exact-support status (`supported` | `unsupported`)
- exact computation results where supported (federal + MA)
- unsupported items list with explanation of why they cannot be computed
- audit findings and confidence notes
- provenance trail (document IDs, tool calls, data sources)

## Fail-Closed Pattern

Inherits from `quarterly-tax`: if facts are outside the supported 2025/2026 US+MA scope, stop and explain. Never estimate unsupported tax computations. Never claim exact results when `assess_exact_support.supported` is `false`.
