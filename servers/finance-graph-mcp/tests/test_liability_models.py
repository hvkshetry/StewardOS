"""Unit tests for extracted liability modeling helpers."""

from datetime import date

import pytest

from liability_models import _compute_refi_metrics, projected_alternative_rate
from test_support.db import FakeRecord


def _projection_inputs() -> dict:
    return {
        "current_rate": 0.06,
        "current_escrow": 0.0,
        "current_payment": 900.0,
        "current_term": 12,
        "model_quality": "observed_history",
        "assumptions_used": ["Used latest liability_rate_terms row dated 2026-01-01 for current_rate"],
        "recurring_extra_principal": 50.0,
        "rate_terms": [
            {
                "id": 1,
                "effective_date": date(2025, 1, 1),
                "interest_rate": 0.04,
                "rate_type": "arm",
                "reset_frequency_months": 6,
                "cap_rate": 0.08,
                "floor_rate": 0.03,
            },
            {
                "id": 2,
                "effective_date": date(2025, 7, 1),
                "interest_rate": 0.05,
                "rate_type": "arm",
                "reset_frequency_months": 6,
                "cap_rate": 0.08,
                "floor_rate": 0.03,
            },
            {
                "id": 3,
                "effective_date": date(2026, 1, 1),
                "interest_rate": 0.06,
                "rate_type": "arm",
                "reset_frequency_months": 6,
                "cap_rate": 0.08,
                "floor_rate": 0.03,
            },
        ],
    }


def test_projected_alternative_rate_averages_future_resets() -> None:
    liability = FakeRecord(next_payment_date=date(2026, 1, 1))

    rate, assumptions = projected_alternative_rate(
        liability_row=liability,
        draw_term_months=12,
        projection_inputs=_projection_inputs(),
    )

    assert rate == pytest.approx(0.065)
    assert any("Projected future rate resets every 6 months" in item for item in assumptions)
    assert any("projected average alternative borrowing rate" in item for item in assumptions)


def test_compute_refi_metrics_uses_rate_terms_and_payment_history_assumptions() -> None:
    liability = FakeRecord(
        id=1,
        outstanding_principal=100000.0,
        interest_rate=0.05,
        remaining_term_months=12,
        escrow_payment=0.0,
        scheduled_payment=900.0,
        next_payment_date=date(2026, 1, 1),
    )
    offer = FakeRecord(
        offered_rate=0.04,
        offered_term_months=12,
        offered_principal=None,
        points_cost=0.0,
        lender_fees=0.0,
        third_party_fees=0.0,
        prepayment_penalty_cost=0.0,
        cash_out_amount=0.0,
        rate_type="fixed",
    )

    metrics = _compute_refi_metrics(
        liability_row=liability,
        offer_row=offer,
        discount_rate_annual=0.05,
        projection_inputs=_projection_inputs(),
    )

    assert metrics["model_quality"] == "observed_history"
    assert metrics["current_schedule_points"] > 0
    assert metrics["new_schedule_points"] > 0
    assert any("Projected future rate resets every 6 months" in item for item in metrics["assumptions_used"])
    assert any("Applied liability_rate_terms cap/floor bounds" in item for item in metrics["assumptions_used"])
