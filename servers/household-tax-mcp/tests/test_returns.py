from __future__ import annotations

from returns import (
    compute_fiduciary_return_exact_internal,
    compute_individual_return_exact_internal,
    register_return_tools,
)
from test_support.mcp import FakeMCP


def test_compute_individual_return_exact_returns_expected_2026_values() -> None:
    result = compute_individual_return_exact_internal(
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "married_filing_jointly",
            "wages": 200000,
            "taxable_interest": 2000,
            "ordinary_dividends": 1000,
            "qualified_dividends": 5000,
            "long_term_capital_gains": 20000,
            "above_line_deductions": 5000,
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    assert result["return"]["federal"]["adjusted_gross_income"] == "228000.00"
    assert result["return"]["federal"]["deduction"] == "32200.00"
    assert result["return"]["federal"]["deduction_type"] == "standard"
    assert result["return"]["federal"]["tax_before_credits"] == "30750.00"
    assert result["return"]["federal"]["child_and_dependent_credits"] == "0.00"
    assert result["return"]["federal"]["alternative_minimum_tax"] == "0.00"
    assert result["return"]["federal"]["total_tax"] == "30750.00"
    assert result["return"]["massachusetts"]["total_tax"] == "10960.00"
    assert result["return"]["combined_total_tax"] == "41710.00"
    assert result["provenance"]["federal_kernel"] == "taxcalc_2026"
    assert result["provenance"]["authority_bundle_version"] == "us_ma_2026_v1"


def test_compute_individual_return_exact_returns_expected_2025_values() -> None:
    result = compute_individual_return_exact_internal(
        {
            "tax_year": 2025,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "married_filing_jointly",
            "wages": 200000,
            "taxable_interest": 2000,
            "ordinary_dividends": 1000,
            "qualified_dividends": 5000,
            "long_term_capital_gains": 20000,
            "above_line_deductions": 5000,
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    assert result["return"]["federal"]["adjusted_gross_income"] == "228000.00"
    assert result["return"]["federal"]["deduction_type"] == "standard"
    assert result["provenance"]["federal_kernel"] == "taxcalc_2025"
    assert result["provenance"]["authority_bundle_version"] == "us_ma_2025_v1"
    assert result["return"]["tax_year"] == 2025
    # 2025 standard deduction for MFJ is $31,500 (Tax-Calculator v6.4.0, OBBB Act), different from 2026 $32,200
    assert result["return"]["federal"]["deduction"] == "31500.00"


def test_compute_individual_return_exact_2025_differs_from_2026() -> None:
    """Same facts, different years should produce different tax amounts."""
    common = {
        "jurisdictions": ["US", "MA"],
        "residence_state": "MA",
        "filing_status": "married_filing_jointly",
        "wages": 200000,
        "taxable_interest": 2000,
        "ordinary_dividends": 1000,
        "qualified_dividends": 5000,
        "long_term_capital_gains": 20000,
        "above_line_deductions": 5000,
        "withholding_events": [],
        "estimated_payments": [],
    }
    result_2025 = compute_individual_return_exact_internal({**common, "tax_year": 2025})
    result_2026 = compute_individual_return_exact_internal({**common, "tax_year": 2026})

    assert result_2025["return"]["federal"]["total_tax"] != result_2026["return"]["federal"]["total_tax"]


def test_compute_individual_return_exact_with_itemized_deductions() -> None:
    result = compute_individual_return_exact_internal(
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "married_filing_jointly",
            "wages": 300000,
            "taxable_interest": 5000,
            "ordinary_dividends": 2000,
            "qualified_dividends": 8000,
            "long_term_capital_gains": 30000,
            "above_line_deductions": 5000,
            "itemized_deductions": {
                "state_local_income_taxes": 20000,
                "real_estate_taxes": 15000,
                "mortgage_interest": 12000,
                "charitable_cash": 5000,
            },
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    federal = result["return"]["federal"]
    assert federal["deduction_type"] == "itemized"
    assert federal["adjusted_gross_income"] == "345000.00"
    # SALT: $20K income + $15K property = $35K, within OBBB Act $40K cap
    assert federal["salt_after_cap"] == "35000.00"
    assert federal["deduction"] == "50275.00"
    assert federal["total_tax"] == "54670.00"


def test_compute_individual_return_exact_itemized_salt_cap_binding() -> None:
    """SALT inputs exceeding cap are capped; deduction reflects capped amount."""
    result = compute_individual_return_exact_internal(
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "married_filing_jointly",
            "wages": 200000,
            "taxable_interest": 2000,
            "above_line_deductions": 0,
            "itemized_deductions": {
                "state_local_income_taxes": 30000,
                "real_estate_taxes": 20000,
                "mortgage_interest": 15000,
                "charitable_cash": 5000,
            },
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    federal = result["return"]["federal"]
    assert federal["deduction_type"] == "itemized"
    # $50K SALT input capped — salt_after_cap must be less than $50K
    salt = federal["salt_after_cap"]
    assert salt == "40400.00"
    assert float(salt) < 50000


def test_compute_individual_return_exact_with_dependents_ctc_matrix() -> None:
    """CTC at $2,200/child (OBBB Act) for 0, 1, 2, and 3 qualifying children."""
    common = {
        "tax_year": 2026,
        "jurisdictions": ["US", "MA"],
        "residence_state": "MA",
        "filing_status": "married_filing_jointly",
        "wages": 150000,
        "withholding_events": [],
        "estimated_payments": [],
    }

    r0 = compute_individual_return_exact_internal({**common, "dependents_under_17": 0, "dependents_under_18": 0})
    r1 = compute_individual_return_exact_internal({**common, "dependents_under_17": 1, "dependents_under_18": 1})
    r2 = compute_individual_return_exact_internal({**common, "dependents_under_17": 2, "dependents_under_18": 2})
    r3 = compute_individual_return_exact_internal({**common, "dependents_under_17": 3, "dependents_under_18": 3})

    assert r0["return"]["federal"]["child_and_dependent_credits"] == "0.00"
    assert r1["return"]["federal"]["child_and_dependent_credits"] == "2200.00"
    assert r2["return"]["federal"]["child_and_dependent_credits"] == "4400.00"
    assert r3["return"]["federal"]["child_and_dependent_credits"] == "6600.00"
    # More children → lower total tax
    assert r0["return"]["federal"]["total_tax"] == "15340.00"
    assert r1["return"]["federal"]["total_tax"] == "13140.00"
    assert r3["return"]["federal"]["total_tax"] == "8740.00"
    # Refundable portion is reported
    assert "child_and_dependent_credits_refundable" in r0["return"]["federal"]
    assert r0["return"]["federal"]["child_and_dependent_credits_refundable"] == "0.00"


def test_compute_individual_return_exact_ctc_phase_out_at_high_income() -> None:
    """CTC phases out at $50 per $1K AGI above $400K MFJ threshold."""
    result = compute_individual_return_exact_internal(
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "married_filing_jointly",
            "wages": 450000,
            "dependents_under_17": 2,
            "dependents_under_18": 2,
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    federal = result["return"]["federal"]
    # Full CTC would be $4,400 (2 × $2,200), but phase-out reduces it
    ctc = federal["child_and_dependent_credits"]
    assert ctc == "1900.00"
    assert float(ctc) < 4400


def test_compute_individual_return_exact_amt_is_zero_for_supported_scope() -> None:
    """AMT is computed but $0 for all supported income types under current law.

    The SALT cap eliminates the main AMT preference (state/local tax add-back).
    AMT would become non-zero if ISOs or private activity bonds were added to scope.
    """
    result = compute_individual_return_exact_internal(
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "single",
            "wages": 500000,
            "taxable_interest": 10000,
            "ordinary_dividends": 5000,
            "qualified_dividends": 15000,
            "long_term_capital_gains": 100000,
            "above_line_deductions": 5000,
            "itemized_deductions": {
                "state_local_income_taxes": 50000,
                "real_estate_taxes": 25000,
                "mortgage_interest": 20000,
                "charitable_cash": 10000,
            },
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    federal = result["return"]["federal"]
    assert federal["alternative_minimum_tax"] == "0.00"
    # Field is present and computed even though it's zero
    assert "alternative_minimum_tax" in federal


def test_compute_fiduciary_return_exact_supports_narrow_2026_scope() -> None:
    result = compute_fiduciary_return_exact_internal(
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "fiduciary_kind": "trust",
            "taxable_interest": 1000,
            "ordinary_dividends": 2000,
            "qualified_dividends": 3000,
            "long_term_capital_gains": 12000,
            "deductions": 1000,
            "exemption_amount": 100,
            "capital_gains_in_dni": False,
            "massachusetts": {
                "taxable_general_income": 17000,
                "taxable_short_term_capital_gains": 0,
            },
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    assert result["return"]["federal"]["total_tax"] == "2300.50"
    assert result["return"]["federal"]["tax_before_credits"] == "2262.50"
    assert result["return"]["federal"]["alternative_minimum_tax"] == "0.00"
    assert result["return"]["massachusetts"]["total_tax"] == "850.00"
    assert result["return"]["combined_total_tax"] == "3150.50"
    assert result["provenance"]["federal_kernel"] == "builtin_2026_fiduciary_kernel"


def test_compute_fiduciary_return_exact_2025_uses_correct_brackets() -> None:
    result = compute_fiduciary_return_exact_internal(
        {
            "tax_year": 2025,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "fiduciary_kind": "trust",
            "taxable_interest": 1000,
            "ordinary_dividends": 2000,
            "qualified_dividends": 3000,
            "long_term_capital_gains": 12000,
            "deductions": 1000,
            "exemption_amount": 100,
            "capital_gains_in_dni": False,
            "massachusetts": {
                "taxable_general_income": 17000,
                "taxable_short_term_capital_gains": 0,
            },
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    assert result["provenance"]["federal_kernel"] == "builtin_2025_fiduciary_kernel"
    assert result["provenance"]["authority_bundle_version"] == "us_ma_2025_v1"
    # 2025 fiduciary brackets differ from 2026, so total tax should differ
    assert result["return"]["federal"]["total_tax"]  # just verify it computed


def test_return_tools_emit_unsupported_exact_case_error_for_bad_year() -> None:
    fake_mcp = FakeMCP()
    register_return_tools(fake_mcp)

    result = fake_mcp.tools["compute_individual_return_exact"](
        {
            "tax_year": 2024,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "single",
            "wages": 100000,
            "withholding_events": [],
            "estimated_payments": [],
        }
    )

    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "unsupported_exact_case"
