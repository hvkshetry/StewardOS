from __future__ import annotations

import pytest

from planning import plan_individual_safe_harbor_internal
from readiness import assess_exact_support_internal, ingest_return_facts_internal, register_readiness_tools
from returns import compute_individual_return_exact_internal
from store import PLAN_STORE, RUN_STORE, load_document, reset_memory_stores
from test_support.mcp import FakeMCP


def _supported_individual(*, tax_year: int = 2026) -> dict:
    return {
        "tax_year": tax_year,
        "jurisdictions": ["US", "MA"],
        "residence_state": "MA",
        "filing_status": "married_filing_jointly",
        "wages": 200000,
        "taxable_interest": 2000,
        "ordinary_dividends": 1000,
        "qualified_dividends": 5000,
        "long_term_capital_gains": 20000,
        "above_line_deductions": 5000,
        "withholding_events": [
            {"payment_date": "2026-03-15", "amount": 12000, "jurisdiction": "US"},
            {"payment_date": "2026-03-15", "amount": 5000, "jurisdiction": "MA"},
        ],
        "estimated_payments": [],
    }


def test_assess_exact_support_rejects_unsupported_field() -> None:
    payload = _supported_individual()
    payload["self_employment_income"] = 15000

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is False
    assert "self_employment_income is outside the exact US+MA scope" in result["unsupported_reasons"]


def test_assess_exact_support_accepts_itemized_deductions() -> None:
    payload = _supported_individual()
    payload["itemized_deductions"] = {
        "state_local_income_taxes": 15000,
        "real_estate_taxes": 10000,
        "mortgage_interest": 8000,
        "charitable_cash": 3000,
    }

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is True
    assert result["normalized_facts"]["itemized_deductions"]["state_local_income_taxes"] == "15000.00"


def test_assess_exact_support_accepts_dependents() -> None:
    payload = _supported_individual()
    payload["dependents_under_17"] = 2
    payload["dependents_under_18"] = 3

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is True
    assert result["normalized_facts"]["dependents_under_17"] == 2
    assert result["normalized_facts"]["dependents_under_18"] == 3


def test_assess_exact_support_rejects_annualized_with_itemized() -> None:
    payload = _supported_individual()
    payload["itemized_deductions"] = {
        "mortgage_interest": 8000,
    }
    payload["annualized_periods"] = [
        {"period_end": "2026-03-31", "wages": 50000},
        {"period_end": "2026-05-31", "wages": 100000},
        {"period_end": "2026-08-31", "wages": 150000},
        {"period_end": "2026-12-31", "wages": 200000},
    ]

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is False
    assert any("annualized_periods and itemized_deductions cannot both be provided" in r for r in result["unsupported_reasons"])


def test_assess_exact_support_accepts_annualized_income_periods() -> None:
    payload = _supported_individual()
    payload["annualized_periods"] = [
        {
            "period_end": "2026-03-31",
            "wages": 50000,
            "taxable_interest": 500,
            "ordinary_dividends": 250,
            "qualified_dividends": 1250,
            "long_term_capital_gains": 5000,
            "above_line_deductions": 1000,
        },
        {
            "period_end": "2026-05-31",
            "wages": 90000,
            "taxable_interest": 900,
            "ordinary_dividends": 500,
            "qualified_dividends": 2500,
            "long_term_capital_gains": 10000,
            "above_line_deductions": 2000,
        },
        {
            "period_end": "2026-08-31",
            "wages": 150000,
            "taxable_interest": 1500,
            "ordinary_dividends": 750,
            "qualified_dividends": 3750,
            "long_term_capital_gains": 15000,
            "above_line_deductions": 3500,
        },
        {
            "period_end": "2026-12-31",
            "wages": 200000,
            "taxable_interest": 2000,
            "ordinary_dividends": 1000,
            "qualified_dividends": 5000,
            "long_term_capital_gains": 20000,
            "above_line_deductions": 5000,
        },
    ]

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is True
    assert result["normalized_facts"]["annualized_periods"][-1]["period_end"] == "2026-12-31"
    assert result["normalized_facts"]["annualized_periods"][-1]["wages"] == "200000.00"


def test_assess_exact_support_2025_supported() -> None:
    payload = _supported_individual(tax_year=2025)
    payload["withholding_events"] = [
        {"payment_date": "2025-03-15", "amount": 12000, "jurisdiction": "US"},
        {"payment_date": "2025-03-15", "amount": 5000, "jurisdiction": "MA"},
    ]

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is True
    assert result["tax_year"] == 2025
    assert result["authority_bundle_version"] == "us_ma_2025_v1"
    assert result["kernels"]["federal_kernel"] == "taxcalc_2025"


def test_assess_exact_support_rejects_2024() -> None:
    payload = _supported_individual()
    payload["tax_year"] = 2024

    result = assess_exact_support_internal("individual", payload)

    assert result["supported"] is False
    assert any("tax_year must be one of" in r for r in result["unsupported_reasons"])


def test_ingest_return_facts_persists_document_and_assessment() -> None:
    reset_memory_stores()

    result = ingest_return_facts_internal(
        "individual",
        _supported_individual(),
        source_name="2026 baseline",
        source_path="/tmp/household_2026.json",
    )

    stored = load_document(result["document_id"])
    assert stored is not None
    assert stored["source_name"] == "2026 baseline"
    assert stored["support_assessment"]["supported"] is True


def test_ty2025_run_persists_correct_authority_bundle() -> None:
    reset_memory_stores()

    result = compute_individual_return_exact_internal(
        _supported_individual(tax_year=2025)
    )

    run_id = result["run_id"]
    stored = RUN_STORE.get(run_id)
    assert stored is not None
    assert stored["tax_year"] == 2025
    assert stored["authority_bundle_version"] == "us_ma_2025_v1"


def test_ty2025_ingest_persists_correct_authority_bundle() -> None:
    reset_memory_stores()

    payload = _supported_individual(tax_year=2025)
    payload["withholding_events"] = [
        {"payment_date": "2025-03-15", "amount": 12000, "jurisdiction": "US"},
        {"payment_date": "2025-03-15", "amount": 5000, "jurisdiction": "MA"},
    ]

    result = ingest_return_facts_internal(
        "individual",
        payload,
        source_name="2025 baseline",
        source_path="/tmp/household_2025.json",
    )

    stored = load_document(result["document_id"])
    assert stored is not None
    assert stored["source_name"] == "2025 baseline"
    assert stored["support_assessment"]["supported"] is True
    assert stored["support_assessment"]["authority_bundle_version"] == "us_ma_2025_v1"


def test_ty2025_plan_persists_correct_authority_bundle() -> None:
    reset_memory_stores()

    facts = {
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
        "prior_year": {
            "total_tax": 30000,
            "adjusted_gross_income": 220000,
            "massachusetts_total_tax": 11000,
            "full_year_return": True,
            "filed": True,
        },
    }

    result = plan_individual_safe_harbor_internal(facts, as_of="2025-09-30")

    plan_id = result["plan_id"]
    stored = PLAN_STORE.get(plan_id)
    assert stored is not None
    assert stored["tax_year"] == 2025
    assert stored["authority_bundle_version"] == "us_ma_2025_v1"


def test_readiness_tools_register_exact_surface() -> None:
    fake_mcp = FakeMCP()
    register_readiness_tools(fake_mcp)

    result = fake_mcp.tools["assess_exact_support"]("individual", _supported_individual())

    assert set(fake_mcp.tools) == {"assess_exact_support", "ingest_return_facts"}
    assert result["status"] == "ok"
    assert result["data"]["supported"] is True
    assert result["data"]["authority_bundle_version"] == "us_ma_2026_v1"
