# Plan: Expand household-tax-mcp — TY2025 + Feature Widening

## Context

The household-tax-mcp server is an exact-scope 2026 US+MA tax engine with 9 tools. It deliberately restricts to a narrow surface (wages, interest, dividends, capital gains, standard deduction only) and fails closed on anything outside scope.

**Critical finding:** Tax-Calculator (v6.4.0, supports TY2013–2035) already models credits, AMT, SE tax, and itemized deductions. The restrictions are purely deliberate design choices in `tax_config.py` and `models.py`. Expanding is mostly "expose what Tax-Calculator already computes" rather than building new computation.

**TY2025 filing is due April 15, 2026 — 1 month away.** This is the highest-ROI expansion.

The external `dma9527/irs-taxpayer-mcp` (39 tools, TY2024/2025, TypeScript) was evaluated and **should not be adopted** — wrong stack, estimation-based, no fiduciary support, no MA exactness, no persistence. However, it validated the breadth of features that Tax-Calculator already handles internally.

---

## Assessment: Should We Expand?

| Feature | Should we? | Rationale |
|---|---|---|
| **TY2025** | **YES — urgent** | Filing deadline April 15. Tax-Calculator handles federal automatically. Need MA + fiduciary constants from Rev. Proc. 2024-40 and MA DOR Circular M 2025. |
| **Itemized deductions** | **YES** | Field already exists on `IndividualTaxFacts`. Tax-Calculator automatically compares std vs. itemized. Minimal code change. Unlocks SALT, mortgage interest, charitable for TY2025 filing. |
| **Credits (CTC)** | **YES** | Tax-Calculator fully computes `ctc_total`. Need `XTOT`, `n24`, `nu18` inputs + extract output. TY2025 CTC is $2,200/child (OBBB Act). High household relevance. |
| **AMT** | **YES** | Tax-Calculator fully computes `c09600`. Just extract the variable. Important for high-income individual + fiduciary returns. |
| **EITC** | **DEFER** | Tax-Calculator computes `eitc`, but eligibility rules are complex (investment income limits, filing status restrictions, EIC filing status). Add after CTC stabilizes. |
| **SE tax + QBI** | **DEFER** | Tax-Calculator computes SE tax (`setax`) and QBI (`qbided`), but QBI has complex phase-outs tied to W-2 wages and qualified property. Needs careful validation. Add after core expansion stabilizes. |
| **Retirement** | **DEFER** | Mostly contribution limit validation, not tax computation. Lower ROI than the above features. |
| **W-4** | **DEFER** | Incremental planning enhancement. Existing `compare_individual_payment_strategies` already covers the withholding decision. |

---

## Implementation Plan

**Delivery**: Single PR covering year parameterization + TY2025 data + credits/AMT/itemized. All phases below ship together.

### Phase 0: Year-Parameterization Refactor (prerequisite for everything)

Thread `tax_year` through the entire codebase so constants, kernels, and due dates are year-aware.

**`tax_config.py`** — refactor from single-year constants to year-keyed lookups:
```python
SUPPORTED_TAX_YEARS = (2025, 2026)
# Replace TAX_YEAR = 2026 with per-call parameter

# Year-keyed constants:
FEDERAL_STANDARD_DEDUCTION = {
    2025: {"single": Decimal("15000.00"), ...},  # Rev. Proc. 2024-40
    2026: {"single": Decimal("16100.00"), ...},  # Rev. Proc. 2025-32
}
# Same pattern for: FEDERAL_ORDINARY_BRACKETS, FEDERAL_PREFERENTIAL_THRESHOLDS,
# FEDERAL_NIIT_THRESHOLDS, FEDERAL_FIDUCIARY_BRACKETS, FEDERAL_FIDUCIARY_PREFERENTIAL_THRESHOLDS,
# MA_SURTAX_THRESHOLD, MA_PERSONAL_EXEMPTION, FEDERAL_INSTALLMENT_DUE_DATES,
# MA_INSTALLMENT_DUE_DATES, ANNUALIZED_INCOME_PERIOD_END_DATES, etc.
```

No backward compat needed — clean break. All constants accessed directly via `CONSTANT[tax_year][filing_status]` pattern.

**`models.py`**:
- Line 803: change `tax_year != TAX_YEAR` → `tax_year not in SUPPORTED_TAX_YEARS`
- Line 861: same for fiduciary
- Line 410: `parse_jurisdictions` — parameterize the error message

**`federal_individual_taxcalc.py`**:
- Accept `tax_year` parameter; pass to `Policy.set_year()` and `Records(start_year=)`
- Tax-Calculator handles all federal bracket/threshold changes automatically

**`returns.py`**:
- Thread `tax_year` from parsed facts through `_individual_federal_breakdown`, `_individual_massachusetts_breakdown`, `_fiduciary_federal_breakdown`, `_fiduciary_massachusetts_breakdown`
- Load year-specific MA constants via `get_config(tax_year)`
- Update `_individual_return_breakdown` and `_fiduciary_return_breakdown` to use `facts.tax_year` instead of global `TAX_YEAR`

**`planning.py`**:
- Thread `tax_year` through all safe-harbor functions
- Load year-specific due dates, triggers, ratios via `get_config(tax_year)`

**`readiness.py`**:
- Thread `tax_year` into provenance output
- Update scope strings to be year-aware

**`store.py`**:
- Already stores `tax_year` in DB records — no schema change needed

**`AUTHORITY_BUNDLE_VERSION`** — make year-specific:
```python
AUTHORITY_BUNDLE_VERSIONS = {
    2025: "us_ma_2025_v1",
    2026: "us_ma_2026_v1",
}
```

**Kernel identifiers** — also year-specific (currently hardcoded as `taxcalc_2026`, `builtin_2026_fiduciary_kernel`, `builtin_2026_ma_kernel`):
```python
FEDERAL_INDIVIDUAL_KERNELS = {2025: "taxcalc_2025", 2026: "taxcalc_2026"}
FEDERAL_FIDUCIARY_KERNELS = {2025: "builtin_2025_fiduciary_kernel", 2026: "builtin_2026_fiduciary_kernel"}
MASSACHUSETTS_KERNELS = {2025: "builtin_2025_ma_kernel", 2026: "builtin_2026_ma_kernel"}
```

**`server.py`**: Update tool docstrings from "2026" to "2025/2026"

**DB migration**: Add seed for `us_ma_2025_v1` authority bundle in `migrations/`:
```sql
INSERT INTO tax.authority_bundles (bundle_version, ...)
VALUES ('us_ma_2025_v1', ...);
```
The existing migration (`20260307_household_tax_exact_runtime.sql`) seeds only `us_ma_2026_v1`. Runs/plans FK to this table, so the 2025 bundle must exist before persisting TY2025 results.

**`store.py`**: Update any hardcoded `AUTHORITY_BUNDLE_VERSION` references to use year-keyed lookup

### Phase 1: TY2025 Data Population

After year parameterization, populate TY2025 constants:

**Federal individual (Tax-Calculator handles automatically)**:
- No constant changes needed — `policy.set_year(2025)` loads correct brackets

**Federal fiduciary (builtin kernel — needs 2025 brackets)**:
- Source: Rev. Proc. 2024-40, IRS Form 1041/8960 Instructions
- `FEDERAL_FIDUCIARY_BRACKETS[2025]`:
  - 10%: $0–$3,150
  - 24%: $3,150–$11,450
  - 35%: $11,450–$15,650
  - 37%: $15,650+
- `FEDERAL_FIDUCIARY_PREFERENTIAL_THRESHOLDS[2025]`:
  - 0% rate top: $3,150
  - 15% rate top: $15,450
- `FEDERAL_FIDUCIARY_NIIT_THRESHOLD[2025]`: $15,650
- `FIDUCIARY_EXEMPTION`: unchanged ($600 estate / $300 simple trust / $100 complex trust)

**Massachusetts (builtin kernel — needs 2025 parameters)**:
- Source: MA DOR Circular M 2025, MA tax rate page, 2025 Form 1 Instructions
- `MA_GENERAL_RATE`: 5.0% (unchanged)
- `MA_SHORT_TERM_CAPITAL_GAINS_RATE`: 8.5% (unchanged since 2023)
- `MA_SURTAX_RATE`: 4% (unchanged)
- `MA_SURTAX_THRESHOLD[2025]`: $1,083,150
- `MA_PERSONAL_EXEMPTION[2025]`: $4,400 single / $8,800 MFJ / $4,400 MFS / $6,800 HOH
- `MA_INSTALLMENT_DUE_DATES[2025]`: 2025-04-15, 2025-06-16, 2025-09-15, 2026-01-15

**Tool descriptions**: Update docstrings from "2026 exact" to "2025/2026 exact"

### Phase 2: Feature Extraction — Credits + AMT + Itemized

These are all "expose what Tax-Calculator already computes":

#### 2a. Itemized Deductions — Category Breakdown

**`tax_config.py`**:
- Remove `"itemized_deductions"` from `INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS`
- Add SALT cap constants (year-keyed — OBBB Act changed TY2025+):
  ```python
  # TY2025+: OBBB Act raised SALT cap to $40K ($20K MFS), phased down above
  # $500K AGI ($250K MFS) but floor of $10K ($5K MFS). Tax-Calculator handles
  # the phase-down internally; we store the base cap for documentation/validation.
  SALT_CAP = {
      2025: {"default": Decimal("40000.00"), "married_filing_separately": Decimal("20000.00")},
      2026: {"default": Decimal("40000.00"), "married_filing_separately": Decimal("20000.00")},
  }
  ```

**`models.py`**: Replace bare `itemized_deductions: Decimal | None` with a structured dataclass:
```python
@dataclass(frozen=True)
class ItemizedDeductions:
    medical_expenses: Decimal = ZERO          # Schedule A line 4 (subject to 7.5% AGI floor)
    state_local_income_taxes: Decimal = ZERO  # SALT income/sales tax (subject to cap)
    real_estate_taxes: Decimal = ZERO         # SALT property tax (subject to cap)
    mortgage_interest: Decimal = ZERO         # Schedule A line 10 (acquisition debt ≤ $750K)
    charitable_cash: Decimal = ZERO           # Schedule A line 12
    charitable_noncash: Decimal = ZERO        # Schedule A line 13
    casualty_loss: Decimal = ZERO             # federally declared disaster only
    other: Decimal = ZERO                     # miscellaneous (limited under TCJA)
```
- Update `IndividualTaxFacts.itemized_deductions` type from `Decimal | None` to `ItemizedDeductions | None`
- Add `_ITEMIZED_FIELDS` set and `parse_itemized_deductions()` function
- Update `_INDIVIDUAL_FIELDS` to include `"itemized_deductions"` as a structured object
- Update `IndividualTaxFacts.to_dict()` to serialize the nested object

**`federal_individual_taxcalc.py`**: Map category fields to Tax-Calculator input variables:
```python
if facts.itemized_deductions is not None:
    itm = facts.itemized_deductions
    record["e17500"] = float(itm.medical_expenses)          # medical (7.5% AGI floor applied by taxcalc)
    record["e18400"] = float(itm.state_local_income_taxes)  # SALT income/sales (cap applied by taxcalc)
    record["e18500"] = float(itm.real_estate_taxes)         # SALT property (cap applied by taxcalc)
    record["e19200"] = float(itm.mortgage_interest)         # mortgage interest
    record["e19800"] = float(itm.charitable_cash)           # charitable cash
    record["e20100"] = float(itm.charitable_noncash)        # charitable non-cash
    record["g20500"] = float(itm.casualty_loss)             # casualty/theft loss
    record["e20400"] = float(itm.other)                     # miscellaneous deductions
```
Tax-Calculator automatically:
- Applies 7.5% AGI floor to medical
- Enforces SALT cap ($10K/$5K MFS)
- Picks max(standard, itemized)

Extract deduction type from output:
```python
standard_deduction = _decimal(calc.array("standard")[0])
itemized_deduction = _decimal(calc.array("c04470")[0])
deduction_type = "standard" if standard_deduction > ZERO else "itemized"
deduction = standard_deduction if standard_deduction > ZERO else itemized_deduction
```

**`returns.py`**: Add `deduction_type` and `salt_after_cap` to federal breakdown output:
```python
"deduction_type": "standard" or "itemized",
"deduction": deduction,
"salt_after_cap": ...,  # extract from taxcalc c18300 (actual SALT after cap, for MA coordination)
```

**Decision: `itemized_deduction_detail` deferred.** Tax-Calculator does not expose per-category post-adjustment values as discrete output variables (only `c04470` total itemized and `c18300` SALT after cap). Emitting a per-category breakdown would require reimplementing Tax-Calculator's adjustment logic (medical 7.5% AGI floor, SALT cap phase-down, mortgage debt limit) outside of Tax-Calculator, creating a fragile maintenance surface. The shipped schema includes `deduction`, `deduction_type`, and `salt_after_cap`, which covers the only adjustment that materially differs from the raw inputs for this household's profile. Full per-category detail can be added in a future phase if Schedule A form-prep requires it.

No backward compat needed — `itemized_deductions` cleanly changes from scalar to object. Update all existing tests to use the new format.

#### 2b. Credits — Child Tax Credit

**`tax_config.py`**: Remove `"child_tax_credit"` from `INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS`

**`models.py`**: Add to `IndividualTaxFacts`:
```python
dependents_under_17: int = 0   # children qualifying for CTC (age < 17 at EOY)
dependents_under_18: int = 0   # children under 18 (for XTOT calculation)
```
Add to `_INDIVIDUAL_FIELDS` and parsing. Validation: `dependents_under_17 <= dependents_under_18`.
Note: these are static per-year so no annualized-period changes needed.

**`federal_individual_taxcalc.py`**: Map to Tax-Calculator input variables (no `num_dependents` variable exists):
```python
n_filers = 2 if facts.filing_status == "married_filing_jointly" else 1
record["XTOT"] = n_filers + facts.dependents_under_18  # total exemptions
record["n24"] = facts.dependents_under_17               # CTC-qualifying children
record["nu18"] = facts.dependents_under_18              # dependents under 18
record["EIC"] = min(facts.dependents_under_17, 3)       # EITC qualifying children (max 3, used even if EITC deferred)
```
Extract from output:
```python
ctc_total = _decimal(calc.array("ctc_total")[0])        # note: includes CTC + ACTC + ODC + ctc_new
ctc_refundable = _decimal(calc.array("ctc_refundable")[0])
```
Note: `ctc_total` is a composite (`c07220 + c11070 + odc + ctc_new`). Label in output as `child_and_dependent_credits` to avoid misleading.

Adjust breakdown to show credits separately: `tax_before_credits`, `child_and_dependent_credits`, `tax_after_credits`

**`returns.py`**: Update federal breakdown output structure to include credit lines

#### 2c. AMT

**`tax_config.py`**: Remove `"alternative_minimum_tax"` from both `INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS` and `FIDUCIARY_RECOGNIZED_UNSUPPORTED_FIELDS`

**`federal_individual_taxcalc.py`**:
- Extract: `amt_liability = _decimal(calc.array("c09600")[0])`
- Tax-Calculator already includes AMT in `iitax` — so total_tax already reflects it
- Just need to expose the AMT component in the breakdown

**Fiduciary AMT**: The builtin fiduciary kernel does NOT compute AMT. Tax-Calculator is individual-only (`MARS` validated 1–5, no fiduciary mode). Options:
1. Add AMT computation to builtin fiduciary kernel (moderate effort — fiduciary AMT uses same 26%/28% rates but compressed exemption)
2. Keep fiduciary AMT as unsupported initially

**Recommendation**: Extract individual AMT from Tax-Calculator (trivial). Keep fiduciary AMT unsupported for now — add to builtin kernel in a future phase.

### Phase 2.5: Edge Cases

**Annualized periods + itemized deductions**: Current annualized periods model only income + above-line deductions, not Schedule A categories. **Fail closed**: if `annualized_periods` and `itemized_deductions` are both present, reject with an unsupported error. Itemized deduction amounts are year-end figures; annualized installment computation should use the full-year itemized total for each period's annualized return.

**Mixed-year trust distribution comparison**: `compare_trust_distribution_strategies` takes `fiduciary_facts` and `beneficiary_facts`. Once both TY2025 and TY2026 are supported, validate that both have the same `tax_year` — reject if mismatched.

**Federal output schema**: Clean break — restructure the breakdown:
```python
"tax_before_credits": ...,
"child_and_dependent_credits": ...,
"alternative_minimum_tax": ...,
"net_investment_income_tax": ...,
"total_tax": ...,  # iitax from taxcalc (includes AMT + credits internally)
```

### Phase 3: Update Skills and Persona Config

**`skills/personas/household-comptroller/quarterly-tax/SKILL.md`**:
- Update supported scope to include TY2025
- Update canonical facts contract with new fields (num_dependents, itemized_deductions)

**`skills/personas/household-comptroller/tax-form-prep/SKILL.md`**:
- Update to reference TY2025 filing
- Update form matrix if needed

**`agent-configs/household-comptroller/AGENTS.md`**:
- Update tool descriptions to reflect expanded scope

### Phase 4: Tests

**Existing test structure**: `tests/test_returns.py`, `tests/test_exact_support.py`, `tests/test_planning.py`, `tests/test_authority_goldens.py`

**New test coverage needed**:
- TY2025 individual return golden values (compare against Tax-Calculator standalone + IRS tax tables)
- TY2025 fiduciary return golden values (using researched 2025 brackets)
- TY2025 safe-harbor planning with 2025 due dates
- Itemized vs. standard deduction selection (categories, SALT cap at $40K)
- CTC with dependents (0, 1, 3 children at various income levels for phase-out)
- AMT exposure in individual breakdown
- Cross-year: ensure TY2025 and TY2026 produce different results for same facts
- Mixed-year rejection: `compare_trust_distribution_strategies` with mismatched years
- Annualized + itemized rejection: fail-closed when both present
- DB persistence: TY2025 authority bundle seed, ingest/run/plan with 2025 bundle
- Readiness: `assess_exact_support` with TY2025 facts returns `supported: true`
- Regression: all existing TY2026 golden tests must still pass

---

## Files Modified

| File | Changes |
|---|---|
| `servers/household-tax-mcp/tax_config.py` | Year-keyed constants, `SUPPORTED_TAX_YEARS`, TY2025 data, remove unsupported fields, year-keyed kernel identifiers |
| `servers/household-tax-mcp/models.py` | Relax year validation, add `ItemizedDeductions` dataclass + parsing, add `dependents_under_17`/`dependents_under_18`, update field sets, annualized+itemized fail-closed |
| `servers/household-tax-mcp/federal_individual_taxcalc.py` | Accept `tax_year`, map itemized categories to taxcalc inputs, add dependent inputs (`XTOT`/`n24`/`nu18`/`EIC`), extract credits (`ctc_total`/`ctc_refundable`) + AMT (`c09600`) + SALT used (`c18300`) |
| `servers/household-tax-mcp/returns.py` | Thread `tax_year`, expanded breakdown output (deduction_type, credits, AMT), year-keyed MA constants |
| `servers/household-tax-mcp/planning.py` | Thread `tax_year`, year-specific due dates/thresholds, mixed-year rejection in distribution comparison |
| `servers/household-tax-mcp/readiness.py` | Thread `tax_year`, year-keyed scope strings and kernel provenance |
| `servers/household-tax-mcp/store.py` | Update hardcoded authority bundle references to year-keyed lookup |
| `servers/household-tax-mcp/server.py` | Update tool docstrings from "2026" to "2025/2026" |
| `servers/household-tax-mcp/migrations/` | New migration to seed `us_ma_2025_v1` authority bundle |
| `servers/household-tax-mcp/tests/test_returns.py` | TY2025 goldens, credits, itemized categories, AMT, updated golden values for new breakdown schema |
| `servers/household-tax-mcp/tests/test_exact_support.py` | TY2025 support assessment, annualized+itemized rejection |
| `servers/household-tax-mcp/tests/test_planning.py` | TY2025 planning, mixed-year rejection |
| `skills/personas/household-comptroller/quarterly-tax/SKILL.md` | Updated scope |
| `skills/personas/household-comptroller/tax-form-prep/SKILL.md` | Updated scope |
| `agent-configs/household-comptroller/AGENTS.md` | Updated tool descriptions |

---

## Verification

1. **Unit tests**: `cd servers/household-tax-mcp && uv run pytest tests/ -v`
2. **Golden value validation**: Compare TY2025 individual results against IRS Tax Table (Pub 17) and Tax-Calculator standalone runs
3. **TY2025 MA validation**: Cross-check MA tax against MA DOR Form 1 instructions
4. **Regression**: All existing TY2026 tests must pass unchanged
5. **Integration**: Run `assess_exact_support` with TY2025 facts — should return `supported: true`
6. **Cross-year**: Same facts with `tax_year: 2025` vs `tax_year: 2026` should produce different tax amounts
7. **Fail-closed**: `tax_year: 2024` should still be rejected
8. **Skill verification**: `make verify-skills` to ensure updated skills pass validation

---

## Deferred (Future Phases)

| Feature | Prerequisite | Notes |
|---|---|---|
| SE tax + QBI | Phase 2 complete | Tax-Calculator computes both (`setax`, `qbided`); QBI phase-out needs careful validation |
| EITC | Phase 2b complete | Tax-Calculator computes (`eitc`); complex eligibility rules (investment income cap, filing status) |
| Retirement contribution validation | None | Limit enforcement, not tax computation |
| W-4 withholding advisor | Phase 0 complete | Incremental planning tool |
| Fiduciary AMT | Investigation needed | Builtin kernel extension (26%/28% rates, compressed exemption) |
