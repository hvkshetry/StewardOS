"""Pure liability modeling helpers for finance-graph analytics."""

from __future__ import annotations

import calendar
import math
from datetime import date
from statistics import median
from typing import Any

import asyncpg

from stewardos_lib.db import float_or_none as _float_or_none


def _add_months(d: date, months: int) -> date:
    month_index = (d.month - 1) + months
    year = d.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _infer_remaining_term_months(row: asyncpg.Record | dict[str, Any]) -> int:
    data = dict(row)
    direct = data.get("remaining_term_months")
    if isinstance(direct, int) and direct > 0:
        return direct

    maturity = data.get("maturity_date")
    if isinstance(maturity, date):
        today = date.today()
        months = (maturity.year - today.year) * 12 + (maturity.month - today.month)
        if maturity.day > today.day:
            months += 1
        if months > 0:
            return months

    amortization = data.get("amortization_months")
    if isinstance(amortization, int) and amortization > 0:
        return amortization

    return 360


def _monthly_payment(principal: float, annual_rate: float | None, term_months: int) -> float:
    if principal <= 0:
        return 0.0
    term = max(1, int(term_months))
    rate = float(annual_rate or 0.0) / 12.0
    if abs(rate) < 1e-12:
        return principal / term
    denom = 1 - math.pow(1 + rate, -term)
    if abs(denom) < 1e-12:
        return principal / term
    return principal * rate / denom


def _build_amortization_schedule(
    *,
    principal: float,
    annual_rate: float | None,
    term_months: int,
    payment_total: float,
    escrow_payment: float,
    start_date: date,
    annual_rate_path: list[float] | None = None,
    recurring_extra_principal: float = 0.0,
) -> list[dict]:
    balance = max(0.0, float(principal))
    payment = max(0.0, float(payment_total))
    escrow = max(0.0, float(escrow_payment))
    extra_principal_target = max(0.0, float(recurring_extra_principal))
    schedule: list[dict] = []

    for i in range(max(0, term_months)):
        if balance <= 0.005:
            break

        due_date = _add_months(start_date, i)
        opening = balance
        period_rate = (
            float(annual_rate_path[i])
            if annual_rate_path is not None and i < len(annual_rate_path)
            else float(annual_rate or 0.0)
        )
        monthly_rate = period_rate / 12.0
        interest = opening * monthly_rate if monthly_rate > 0 else 0.0
        base_principal_component = max(0.0, payment - escrow - interest)

        if base_principal_component > opening:
            base_principal_component = opening
            payment_effective = base_principal_component + interest + escrow
        else:
            payment_effective = payment

        payment_available_for_interest = max(0.0, payment_effective - escrow)
        interest_shortfall = max(0.0, interest - payment_available_for_interest)
        escrow_shortfall = max(0.0, escrow - payment_effective)
        extra_principal_component = 0.0
        if interest_shortfall <= 0.0 and payment_effective >= escrow + interest:
            extra_principal_component = min(
                extra_principal_target,
                max(0.0, opening - base_principal_component),
            )

        principal_component = min(opening, base_principal_component + extra_principal_component)
        closing = max(0.0, opening - principal_component + interest_shortfall)

        schedule.append(
            {
                "due_date": due_date,
                "opening_balance": opening,
                "payment_total": payment_effective + extra_principal_component,
                "payment_principal": principal_component,
                "payment_interest": interest,
                "payment_escrow": escrow,
                "closing_balance": closing,
                "interest_shortfall": interest_shortfall,
                "escrow_shortfall": escrow_shortfall,
                "annual_rate": period_rate,
                "extra_principal": extra_principal_component,
            }
        )
        balance = closing

    return schedule


def _pv_amounts(amounts: list[float], annual_discount_rate: float) -> float:
    discount = max(-0.99, float(annual_discount_rate)) / 12.0
    pv = 0.0
    for i, amount in enumerate(amounts, start=1):
        if abs(discount) < 1e-12:
            pv += amount
            continue
        pv += amount / math.pow(1 + discount, i)
    return pv


def _recommendation_from_refi(npv_savings: float, break_even_months: float | None, term_months: int) -> str:
    if npv_savings <= 0:
        return "hold"
    if break_even_months is None:
        return "watch"
    if break_even_months <= max(1, term_months):
        return "recommend"
    return "watch"


def _latest_term(rate_terms: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rate_terms:
        return None
    return max(rate_terms, key=lambda item: (item.get("effective_date") or date.min, int(item.get("id") or 0)))


def _observed_rate_step(rate_terms: list[dict[str, Any]]) -> float | None:
    sorted_terms = sorted(
        (term for term in rate_terms if term.get("interest_rate") is not None),
        key=lambda item: (item.get("effective_date") or date.min, int(item.get("id") or 0)),
    )
    if len(sorted_terms) < 2:
        return None
    deltas = [
        float(sorted_terms[idx]["interest_rate"]) - float(sorted_terms[idx - 1]["interest_rate"])
        for idx in range(1, len(sorted_terms))
    ]
    non_zero = [delta for delta in deltas if abs(delta) > 1e-9]
    if non_zero:
        return non_zero[-1]
    return deltas[-1] if deltas else None


def _build_projected_rate_path(
    *,
    start_date: date,
    term_months: int,
    current_rate: float,
    rate_terms: list[dict[str, Any]],
    assumptions_used: list[str],
) -> list[float]:
    latest_term = _latest_term(rate_terms)
    base_rate = float(current_rate or 0.0)
    path: list[float] = []

    if latest_term is None:
        assumptions_used.append("Held current_rate flat because no liability_rate_terms history was available")
        return [base_rate] * max(0, term_months)

    latest_rate = _float_or_none(latest_term.get("interest_rate"))
    if latest_rate is not None:
        base_rate = latest_rate

    cap_rate = _float_or_none(latest_term.get("cap_rate"))
    floor_rate = _float_or_none(latest_term.get("floor_rate"))
    rate_type = str(latest_term.get("rate_type") or "fixed").strip().lower()
    reset_frequency = latest_term.get("reset_frequency_months")
    observed_step = _observed_rate_step(rate_terms)
    latest_effective = latest_term.get("effective_date") or start_date
    next_reset_date = None

    if rate_type != "fixed" and isinstance(reset_frequency, int) and reset_frequency > 0:
        next_reset_date = _add_months(latest_effective, reset_frequency)
        if observed_step is None:
            assumptions_used.append(
                "Held projected liability rate flat after latest known rate term because no observed reset delta was available"
            )
        else:
            assumptions_used.append(
                f"Projected future rate resets every {reset_frequency} months using last observed rate delta {observed_step:.6f}"
            )
        if cap_rate is not None or floor_rate is not None:
            assumptions_used.append("Applied liability_rate_terms cap/floor bounds while projecting future resets")
    else:
        assumptions_used.append("Used explicit current liability_rate_terms row without additional future rate resets")

    for i in range(max(0, term_months)):
        due_date = _add_months(start_date, i)
        applicable_terms = [
            term for term in rate_terms if (term.get("effective_date") or start_date) <= due_date
        ]
        if applicable_terms:
            applicable = _latest_term(applicable_terms)
            assert applicable is not None
            explicit_rate = _float_or_none(applicable.get("interest_rate"))
            if explicit_rate is not None:
                base_rate = explicit_rate
                cap_rate = _float_or_none(applicable.get("cap_rate"))
                floor_rate = _float_or_none(applicable.get("floor_rate"))
                rate_type = str(applicable.get("rate_type") or rate_type).strip().lower()
                reset_frequency = applicable.get("reset_frequency_months")
                latest_effective = applicable.get("effective_date") or latest_effective
                if rate_type != "fixed" and isinstance(reset_frequency, int) and reset_frequency > 0:
                    next_reset_date = _add_months(latest_effective, reset_frequency)

        if (
            rate_type != "fixed"
            and isinstance(reset_frequency, int)
            and reset_frequency > 0
            and next_reset_date is not None
            and due_date >= next_reset_date
            and observed_step is not None
        ):
            while due_date >= next_reset_date:
                base_rate += observed_step
                next_reset_date = _add_months(next_reset_date, reset_frequency)

        if cap_rate is not None:
            base_rate = min(base_rate, cap_rate)
        if floor_rate is not None:
            base_rate = max(base_rate, floor_rate)

        path.append(base_rate)

    return path


def _summarize_payment_history(
    *,
    liability: dict[str, Any],
    payment_rows: list[dict[str, Any]],
    assumptions_used: list[str],
) -> tuple[float | None, float, float, int]:
    scheduled_payment = _float_or_none(liability.get("scheduled_payment"))
    current_escrow = _float_or_none(liability.get("escrow_payment")) or 0.0
    recurring_extra_principal = 0.0
    delinquent_count = 0

    observed_totals = [float(row["amount_total"]) for row in payment_rows if row.get("amount_total") is not None]
    observed_escrows = [float(row["amount_escrow"]) for row in payment_rows if row.get("amount_escrow") is not None]

    if observed_escrows:
        observed_escrow = float(median(observed_escrows))
        if abs(observed_escrow - current_escrow) > 0.01:
            current_escrow = observed_escrow
            assumptions_used.append(
                f"Used median escrow from last {len(observed_escrows)} liability_payments rows for escrow_payment"
            )

    current_payment = scheduled_payment
    if observed_totals:
        observed_payment = float(median(observed_totals))
        if current_payment is None:
            current_payment = observed_payment
            assumptions_used.append(
                f"Used median of last {len(observed_totals)} liability_payments rows for payment_total"
            )
        else:
            delta = observed_payment - current_payment
            if delta > 1.0:
                recurring_extra_principal = delta
                assumptions_used.append(
                    f"Inferred recurring extra principal from payment history premium of {delta:.2f} over scheduled_payment"
                )
        delinquent_count = sum(
            1 for total in observed_totals if current_payment is not None and total + 1.0 < current_payment
        )
        if delinquent_count:
            assumptions_used.append(
                f"Observed {delinquent_count} recent liability_payments rows below the expected payment amount"
            )

    return current_payment, current_escrow, recurring_extra_principal, delinquent_count


async def _load_liability_projection_inputs(
    *,
    pool: asyncpg.Pool,
    liability_row: asyncpg.Record,
) -> dict:
    liability = dict(liability_row)
    liability_id = int(liability_row["id"])
    rate_term_rows = await pool.fetch(
        """SELECT *
           FROM liability_rate_terms
           WHERE liability_id = $1
           ORDER BY effective_date ASC, id ASC""",
        liability_id,
    )
    payment_rows_raw = await pool.fetch(
        """SELECT amount_total, amount_principal, amount_interest, amount_escrow, payment_date
           FROM liability_payments
           WHERE liability_id = $1
           ORDER BY payment_date DESC, id DESC
           LIMIT 24""",
        liability_id,
    )
    rate_terms = [dict(row) for row in rate_term_rows]
    payment_rows = [dict(row) for row in payment_rows_raw]

    current_rate = _float_or_none(liability.get("interest_rate")) or 0.0
    assumptions_used: list[str] = []

    latest_rate_term = _latest_term(rate_terms)
    if latest_rate_term is not None:
        latest_rate = _float_or_none(latest_rate_term.get("interest_rate"))
        if latest_rate is not None:
            current_rate = latest_rate
            assumptions_used.append(
                f"Used latest liability_rate_terms row dated {latest_rate_term['effective_date'].isoformat()} for current_rate"
            )

    current_payment, current_escrow, recurring_extra_principal, delinquent_count = _summarize_payment_history(
        liability=liability,
        payment_rows=payment_rows,
        assumptions_used=assumptions_used,
    )

    if current_payment is None:
        current_payment = _monthly_payment(
            float(liability.get("outstanding_principal") or 0.0),
            current_rate,
            _infer_remaining_term_months(liability_row),
        ) + current_escrow
        assumptions_used.append(
            "Derived payment_total from outstanding principal, projected current_rate, remaining term, and escrow"
        )

    if len(rate_terms) >= 2 and len(payment_rows) >= 6:
        model_quality = "observed_history"
    elif rate_terms or payment_rows:
        model_quality = "hybrid"
    else:
        model_quality = "approximate"

    return {
        "current_rate": current_rate,
        "current_escrow": current_escrow,
        "current_payment": current_payment,
        "current_term": _infer_remaining_term_months(liability_row),
        "model_quality": model_quality,
        "assumptions_used": assumptions_used,
        "rate_terms": rate_terms,
        "payment_history_count": len(payment_rows),
        "recurring_extra_principal": recurring_extra_principal,
        "delinquent_payment_count": delinquent_count,
    }


def _compute_refi_metrics(
    *,
    liability_row: asyncpg.Record,
    offer_row: asyncpg.Record,
    discount_rate_annual: float,
    projection_inputs: dict | None = None,
) -> dict:
    liability = dict(liability_row)
    offer = dict(offer_row)

    principal_current = float(liability.get("outstanding_principal") or 0.0)
    current_rate = (
        float(projection_inputs["current_rate"])
        if projection_inputs and projection_inputs.get("current_rate") is not None
        else (_float_or_none(liability.get("interest_rate")) or 0.0)
    )
    current_term = (
        int(projection_inputs["current_term"])
        if projection_inputs and projection_inputs.get("current_term") is not None
        else _infer_remaining_term_months(liability_row)
    )
    current_escrow = (
        float(projection_inputs["current_escrow"])
        if projection_inputs and projection_inputs.get("current_escrow") is not None
        else (_float_or_none(liability.get("escrow_payment")) or 0.0)
    )
    current_payment = (
        float(projection_inputs["current_payment"])
        if projection_inputs and projection_inputs.get("current_payment") is not None
        else _float_or_none(liability.get("scheduled_payment"))
    )
    recurring_extra_principal = (
        float(projection_inputs.get("recurring_extra_principal") or 0.0) if projection_inputs else 0.0
    )
    assumptions_used = list(projection_inputs.get("assumptions_used") or []) if projection_inputs else []
    model_quality = str(projection_inputs.get("model_quality") or "approximate") if projection_inputs else "approximate"
    start_date = liability.get("next_payment_date") or date.today()

    current_rate_path = _build_projected_rate_path(
        start_date=start_date,
        term_months=current_term,
        current_rate=current_rate,
        rate_terms=list(projection_inputs.get("rate_terms") or []) if projection_inputs else [],
        assumptions_used=assumptions_used,
    )

    principal_new = _float_or_none(offer.get("offered_principal"))
    if principal_new is None or principal_new <= 0:
        principal_new = principal_current
    offer_rate = _float_or_none(offer.get("offered_rate")) or 0.0
    offer_term = int(offer.get("offered_term_months") or current_term)
    new_payment = _monthly_payment(principal_new, offer_rate, offer_term) + current_escrow
    offer_rate_type = str(offer.get("rate_type") or "fixed").strip().lower()
    if offer_rate_type != "fixed":
        assumptions_used.append("Modeled refinance offer as flat offered_rate because future offer reset terms were not provided")

    current_schedule = _build_amortization_schedule(
        principal=principal_current,
        annual_rate=current_rate,
        annual_rate_path=current_rate_path,
        term_months=current_term,
        payment_total=current_payment,
        escrow_payment=current_escrow,
        start_date=start_date,
        recurring_extra_principal=recurring_extra_principal,
    )
    new_schedule = _build_amortization_schedule(
        principal=principal_new,
        annual_rate=offer_rate,
        term_months=offer_term,
        payment_total=new_payment,
        escrow_payment=current_escrow,
        start_date=start_date,
    )

    current_amounts = [float(item["payment_total"]) for item in current_schedule]
    new_amounts = [float(item["payment_total"]) for item in new_schedule]

    pv_current = _pv_amounts(current_amounts, discount_rate_annual)
    pv_new_payments = _pv_amounts(new_amounts, discount_rate_annual)

    closing_costs = (
        (_float_or_none(offer.get("points_cost")) or 0.0)
        + (_float_or_none(offer.get("lender_fees")) or 0.0)
        + (_float_or_none(offer.get("third_party_fees")) or 0.0)
        + (_float_or_none(offer.get("prepayment_penalty_cost")) or 0.0)
    )
    cash_out_amount = _float_or_none(offer.get("cash_out_amount")) or 0.0
    pv_new_total = pv_new_payments + closing_costs - cash_out_amount

    npv_savings = pv_current - pv_new_total
    monthly_savings = current_payment - new_payment
    break_even_months = None
    if monthly_savings > 0.0 and closing_costs > 0.0:
        break_even_months = closing_costs / monthly_savings

    recommendation = _recommendation_from_refi(npv_savings, break_even_months, current_term)
    return {
        "npv_savings": npv_savings,
        "break_even_months": break_even_months,
        "annual_payment_change": (new_payment - current_payment) * 12.0,
        "recommendation": recommendation,
        "current_monthly_payment": current_payment,
        "new_monthly_payment": new_payment,
        "current_term_months": current_term,
        "new_term_months": offer_term,
        "pv_current_payments": pv_current,
        "pv_new_payments": pv_new_payments,
        "closing_costs": closing_costs,
        "cash_out_amount": cash_out_amount,
        "pv_new_total": pv_new_total,
        "current_schedule_points": len(current_schedule),
        "new_schedule_points": len(new_schedule),
        "model_quality": model_quality,
        "assumptions_used": assumptions_used,
    }


def projected_alternative_rate(
    *,
    liability_row: asyncpg.Record,
    draw_term_months: int,
    projection_inputs: dict,
) -> tuple[float, list[str]]:
    assumptions_used: list[str] = []
    start_date = dict(liability_row).get("next_payment_date") or date.today()
    rate_path = _build_projected_rate_path(
        start_date=start_date,
        term_months=max(1, int(draw_term_months)),
        current_rate=float(projection_inputs.get("current_rate") or 0.0),
        rate_terms=list(projection_inputs.get("rate_terms") or []),
        assumptions_used=assumptions_used,
    )
    effective_rate = sum(rate_path) / len(rate_path) if rate_path else float(projection_inputs.get("current_rate") or 0.0)
    if rate_path:
        assumptions_used.append("Used projected average alternative borrowing rate from liability_rate_terms history")
    return effective_rate, assumptions_used
