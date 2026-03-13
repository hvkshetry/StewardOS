from __future__ import annotations

import pytest

from planning import (
    compare_individual_payment_strategies_internal,
    compare_trust_distribution_strategies_internal,
    plan_fiduciary_safe_harbor_internal,
    plan_individual_safe_harbor_internal,
    register_planning_tools,
)
from test_support.mcp import FakeMCP


def _individual_facts(*, tax_year: int = 2026) -> dict:
    return {
        "tax_year": tax_year,
        "jurisdictions": ["US", "MA"],
        "residence_state": "MA",
        "filing_status": "married_filing_jointly",
        "wages": 240000,
        "taxable_interest": 4000,
        "ordinary_dividends": 2000,
        "qualified_dividends": 6000,
        "long_term_capital_gains": 15000,
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


def _fiduciary_facts(*, tax_year: int = 2026) -> dict:
    return {
        "tax_year": tax_year,
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
        "prior_year": {
            "total_tax": 2000,
            "adjusted_gross_income": 17000,
            "full_year_return": True,
            "filed": True,
            "first_year_massachusetts_fiduciary": False,
        },
    }


def _annualized_backloaded_individual_facts(*, tax_year: int = 2026) -> dict:
    period_end_dates = {
        2025: ["2025-03-31", "2025-05-31", "2025-08-31", "2025-12-31"],
        2026: ["2026-03-31", "2026-05-31", "2026-08-31", "2026-12-31"],
    }
    dates = period_end_dates[tax_year]
    return {
        "tax_year": tax_year,
        "jurisdictions": ["US", "MA"],
        "residence_state": "MA",
        "filing_status": "single",
        "wages": 0,
        "taxable_interest": 0,
        "ordinary_dividends": 0,
        "qualified_dividends": 0,
        "long_term_capital_gains": 200000,
        "above_line_deductions": 0,
        "withholding_events": [],
        "estimated_payments": [],
        "annualized_periods": [
            {"period_end": dates[0], "long_term_capital_gains": 0},
            {"period_end": dates[1], "long_term_capital_gains": 0},
            {"period_end": dates[2], "long_term_capital_gains": 0},
            {"period_end": dates[3], "long_term_capital_gains": 200000},
        ],
    }


def _annualized_backloaded_fiduciary_facts() -> dict:
    return {
        "tax_year": 2026,
        "jurisdictions": ["US", "MA"],
        "residence_state": "MA",
        "fiduciary_kind": "trust",
        "taxable_interest": 0,
        "ordinary_dividends": 0,
        "qualified_dividends": 0,
        "long_term_capital_gains": 24000,
        "deductions": 1000,
        "exemption_amount": 100,
        "capital_gains_in_dni": False,
        "withholding_events": [],
        "estimated_payments": [],
        "annualized_periods": [
            {"period_end": "2026-03-31", "long_term_capital_gains": 0, "deductions": 0},
            {"period_end": "2026-05-31", "long_term_capital_gains": 0, "deductions": 0},
            {"period_end": "2026-08-31", "long_term_capital_gains": 0, "deductions": 0},
            {"period_end": "2026-12-31", "long_term_capital_gains": 24000, "deductions": 1000},
        ],
        "prior_year": {
            "total_tax": 20000,
            "adjusted_gross_income": 12000,
            "massachusetts_total_tax": 500,
            "full_year_return": True,
            "filed": True,
            "first_year_massachusetts_fiduciary": True,
        },
    }


def test_compare_individual_payment_strategies_prefers_ratable_withholding_after_missed_due_dates() -> None:
    result = compare_individual_payment_strategies_internal(_individual_facts(), as_of="2026-09-30")

    assert result["recommended_strategy"] == "ratable_withholding_catch_up"
    assert result["strategies"][0]["strategy_id"] == "ratable_withholding_catch_up"
    assert result["strategies"][0]["installment_safe_harbor_satisfied"] is True


def test_compare_individual_payment_strategies_supports_annualized_income_method() -> None:
    result = compare_individual_payment_strategies_internal(
        _annualized_backloaded_individual_facts(),
        as_of="2026-09-30",
    )

    assert result["recommended_strategy"] == "estimated_payments"
    assert result["strategies"][0]["installment_safe_harbor_satisfied"] is True
    assert result["safe_harbor"]["federal"]["annualized_income_method_used"] is True
    assert result["safe_harbor"]["federal"]["installments"][2]["required_basis"] == "annualized_income"
    assert result["safe_harbor"]["federal"]["installments"][2]["required_cumulative"] == "0.00"
    assert result["strategies"][0]["actions"] == [
        {"action": "make_estimated_payment", "jurisdiction": "US", "due_date": "2027-01-15", "amount": "18150.75"},
        {"action": "make_estimated_payment", "jurisdiction": "MA", "due_date": "2027-01-15", "amount": "7824.00"},
    ]


def test_compare_individual_payment_strategies_2025() -> None:
    result = compare_individual_payment_strategies_internal(
        _individual_facts(tax_year=2025),
        as_of="2025-09-30",
    )

    assert result["tax_year"] == 2025
    assert result["provenance"]["authority_bundle_version"] == "us_ma_2025_v1"
    assert result["recommended_strategy"] in {"estimated_payments", "ratable_withholding_catch_up"}
    # TY2025 uses 2025-specific due dates (June 16 weekend shift)
    federal_dates = [i["due_date"] for i in result["safe_harbor"]["federal"]["installments"]]
    assert federal_dates == ["2025-04-15", "2025-06-16", "2025-09-15", "2026-01-15"]


def test_safe_harbor_plan_tools_emit_exact_actions() -> None:
    individual_plan = plan_individual_safe_harbor_internal(_individual_facts(), as_of="2026-09-30")
    fiduciary_plan = plan_fiduciary_safe_harbor_internal(_fiduciary_facts(), as_of="2026-09-30")

    assert individual_plan["recommended_strategy"] == "ratable_withholding_catch_up"
    assert individual_plan["recommended_actions"]
    assert fiduciary_plan["recommended_strategy"] == "estimated_payments"
    assert fiduciary_plan["recommended_actions"]


def test_fiduciary_safe_harbor_supports_annualized_income_and_first_year_massachusetts_rule() -> None:
    plan = plan_fiduciary_safe_harbor_internal(
        _annualized_backloaded_fiduciary_facts(),
        as_of="2026-09-30",
    )

    assert plan["recommended_strategy"] == "estimated_payments"
    assert plan["safe_harbor"]["federal"]["annualized_income_method_used"] is True
    assert plan["safe_harbor"]["massachusetts"]["annualized_income_method_used"] is True
    assert plan["safe_harbor"]["massachusetts"]["prior_year_safe_harbor_available"] is False
    assert (
        plan["safe_harbor"]["massachusetts"]["safe_harbor_rule"]
        == "massachusetts_80_percent_current_year_first_year_fiduciary"
    )
    assert plan["massachusetts_first_year_fiduciary"] is True
    assert plan["safe_harbor"]["federal"]["installments"][2]["required_basis"] == "annualized_income"
    assert plan["recommended_actions"] == [
        {"action": "make_estimated_payment", "jurisdiction": "US", "due_date": "2027-01-15", "amount": "3184.65"},
        {"action": "make_estimated_payment", "jurisdiction": "MA", "due_date": "2027-01-15", "amount": "916.00"},
    ]


def test_compare_trust_distribution_strategies_ranks_candidates() -> None:
    result = compare_trust_distribution_strategies_internal(
        _fiduciary_facts(),
        _individual_facts(),
        [0, 2000, 4000],
    )

    assert result["recommended_distribution_amount"] in {"0.00", "2000.00", "4000.00"}
    assert len(result["options"]) == 3
    assert result["options"][0]["combined_incremental_tax"] <= result["options"][1]["combined_incremental_tax"]


def test_compare_trust_distribution_strategies_rejects_mixed_year() -> None:
    with pytest.raises(ValueError, match="must match"):
        compare_trust_distribution_strategies_internal(
            _fiduciary_facts(tax_year=2025),
            _individual_facts(tax_year=2026),
            [0, 2000],
        )


def test_planning_tools_register_exact_surface() -> None:
    fake_mcp = FakeMCP()
    register_planning_tools(fake_mcp)

    result = fake_mcp.tools["plan_individual_safe_harbor"](_individual_facts(), "2026-09-30")

    assert set(fake_mcp.tools) == {
        "plan_individual_safe_harbor",
        "plan_fiduciary_safe_harbor",
        "compare_individual_payment_strategies",
        "compare_trust_distribution_strategies",
    }
    assert result["status"] == "ok"
    assert result["data"]["recommended_strategy"] == "ratable_withholding_catch_up"


def test_planning_tools_fail_closed_with_explicit_error_code() -> None:
    fake_mcp = FakeMCP()
    register_planning_tools(fake_mcp)

    result = fake_mcp.tools["plan_individual_safe_harbor"](
        {
            "tax_year": 2026,
            "jurisdictions": ["US", "MA"],
            "residence_state": "MA",
            "filing_status": "single",
            "wages": 100000,
            "self_employment_income": 25000,
            "withholding_events": [],
            "estimated_payments": [],
        },
        "2026-09-30",
    )

    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "unsupported_exact_case"
