import json
from datetime import date

from stewardos_lib.db import float_or_none as _float_or_none
from stewardos_lib.domain_ops import parse_iso_date as _parse_iso_date

from liability_models import (
    _build_amortization_schedule,
    _infer_remaining_term_months,
    _monthly_payment,
)


def build_amortization_payload(
    *,
    liability,
    months: int | None,
    annual_rate_override: float | None,
    payment_total_override: float | None,
    escrow_payment_override: float | None,
    start_date: str | None,
) -> dict:
    principal = float(liability["outstanding_principal"] or 0.0)
    if principal <= 0:
        raise ValueError("outstanding_principal must be > 0")

    base_start = _parse_iso_date(start_date, "start_date")
    if base_start is None:
        base_start = liability["next_payment_date"] or date.today()

    term_months = months if isinstance(months, int) and months > 0 else _infer_remaining_term_months(liability)
    annual_rate = annual_rate_override if annual_rate_override is not None else (_float_or_none(liability["interest_rate"]) or 0.0)
    escrow_payment = (
        escrow_payment_override
        if escrow_payment_override is not None
        else (_float_or_none(liability["escrow_payment"]) or 0.0)
    )
    payment_total = payment_total_override
    if payment_total is None:
        payment_total = _float_or_none(liability["scheduled_payment"])
    if payment_total is None:
        payment_total = _monthly_payment(principal, annual_rate, term_months) + escrow_payment

    schedule = _build_amortization_schedule(
        principal=principal,
        annual_rate=annual_rate,
        term_months=term_months,
        payment_total=float(payment_total),
        escrow_payment=float(escrow_payment),
        start_date=base_start,
    )

    total_interest = sum(float(item["payment_interest"]) for item in schedule)
    total_payments = sum(float(item["payment_total"]) for item in schedule)
    ending_balance = float(schedule[-1]["closing_balance"]) if schedule else principal
    return {
        "schedule": schedule,
        "principal": principal,
        "term_months": term_months,
        "annual_rate": annual_rate,
        "payment_total": payment_total,
        "total_payments": total_payments,
        "total_interest": total_interest,
        "ending_balance": ending_balance,
    }


async def persist_amortization_schedule(
    conn,
    *,
    liability_id: int,
    scenario_tag: str,
    schedule: list[dict],
    annual_rate: float,
    term_months: int,
) -> None:
    await conn.execute(
        "DELETE FROM liability_cashflow_schedule WHERE liability_id = $1 AND scenario_tag = $2",
        liability_id,
        scenario_tag,
    )

    for row in schedule:
        await conn.execute(
            """INSERT INTO liability_cashflow_schedule (
                   liability_id, due_date, opening_balance, payment_total, payment_principal,
                   payment_interest, payment_escrow, closing_balance, scenario_tag, source, metadata
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'generated',$10::jsonb)""",
            liability_id,
            row["due_date"],
            row["opening_balance"],
            row["payment_total"],
            row["payment_principal"],
            row["payment_interest"],
            row["payment_escrow"],
            row["closing_balance"],
            scenario_tag,
            json.dumps(
                {
                    "annual_rate": annual_rate,
                    "term_months": term_months,
                    "interest_shortfall": row["interest_shortfall"],
                    "escrow_shortfall": row["escrow_shortfall"],
                }
            ),
        )
