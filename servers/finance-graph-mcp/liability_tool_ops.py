import json
import uuid
from datetime import date
from hashlib import sha256

import asyncpg

from stewardos_lib.db import float_or_none as _float_or_none, row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import (
    normalize_currency_code as _normalize_currency_code,
    parse_iso_date as _parse_iso_date,
)
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import error_response as _error_response, ok_response as _ok_response
from liability_models import (
    _add_months,
    _compute_refi_metrics,
    _load_liability_projection_inputs,
    _monthly_payment,
    _pv_amounts,
    projected_alternative_rate as _projected_alternative_rate,
)
from liability_schedule_ops import (
    build_amortization_payload as _build_amortization_payload,
    persist_amortization_schedule as _persist_amortization_schedule,
)

_SUPPORTED_PAYMENT_FREQUENCIES = {
    "monthly": 1,
    "quarterly": 3,
    "annual": 12,
}


def _normalize_payment_frequency(value: str | None) -> str:
    normalized = (value or "monthly").strip().lower()
    if normalized not in _SUPPORTED_PAYMENT_FREQUENCIES:
        allowed = ", ".join(sorted(_SUPPORTED_PAYMENT_FREQUENCIES))
        raise ValueError(f"payment_frequency must be one of: {allowed}")
    return normalized


def _advance_next_payment_date(
    current_next_payment_date: date | None,
    *,
    payment_date: date,
    payment_frequency: str,
) -> date:
    anchor = current_next_payment_date or payment_date
    next_date = _add_months(anchor, _SUPPORTED_PAYMENT_FREQUENCIES[payment_frequency])
    while next_date <= payment_date:
        next_date = _add_months(next_date, _SUPPORTED_PAYMENT_FREQUENCIES[payment_frequency])
    return next_date


def _derived_payment_idempotency_key(
    *,
    liability_id: int,
    payment_date: date,
    amount_total: float,
    amount_principal: float,
    amount_interest: float | None,
    amount_escrow: float | None,
    source: str,
    reference: str | None,
) -> str:
    payload = {
        "liability_id": liability_id,
        "payment_date": payment_date.isoformat(),
        "amount_total": round(float(amount_total), 6),
        "amount_principal": round(float(amount_principal), 6),
        "amount_interest": round(float(amount_interest or 0.0), 6),
        "amount_escrow": round(float(amount_escrow or 0.0), 6),
        "source": (source or "").strip().lower(),
        "reference": (reference or "").strip(),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_payment_split(
    *,
    amount_total: float,
    amount_principal: float | None,
    amount_interest: float | None,
    amount_escrow: float | None,
) -> tuple[float, float | None, float | None]:
    total = float(amount_total)
    if total <= 0:
        raise ValueError("amount_total must be > 0")

    for field_name, value in (
        ("amount_principal", amount_principal),
        ("amount_interest", amount_interest),
        ("amount_escrow", amount_escrow),
    ):
        if value is not None and float(value) < 0:
            raise ValueError(f"{field_name} cannot be negative")

    interest_component = float(amount_interest) if amount_interest is not None else 0.0
    escrow_component = float(amount_escrow) if amount_escrow is not None else 0.0
    if amount_principal is None:
        principal_component = total - interest_component - escrow_component
        if principal_component < -0.005:
            raise ValueError("Payment split exceeds amount_total")
        principal_component = round(max(0.0, principal_component), 6)
    else:
        principal_component = float(amount_principal)
        if abs((principal_component + interest_component + escrow_component) - total) > 0.01:
            raise ValueError("Payment split must sum to amount_total")

    return principal_component, amount_interest, amount_escrow


async def _resolve_borrower(
    *,
    pool: asyncpg.Pool,
    borrower_person_id: int | None,
    borrower_entity_id: int | None,
) -> tuple[int | None, int | None]:
    """Validate and return (borrower_person_id, borrower_entity_id) — exactly one must be set."""
    if borrower_person_id is not None and borrower_entity_id is not None:
        raise ValueError("Provide exactly one of borrower_person_id or borrower_entity_id, not both")

    if borrower_person_id is not None:
        exists = await pool.fetchval("SELECT 1 FROM people WHERE id = $1", borrower_person_id)
        if not exists:
            raise ValueError(f"borrower_person_id {borrower_person_id} not found in core.people")
        return borrower_person_id, None

    if borrower_entity_id is not None:
        exists = await pool.fetchval("SELECT 1 FROM entities WHERE id = $1", borrower_entity_id)
        if not exists:
            raise ValueError(f"borrower_entity_id {borrower_entity_id} not found in core.entities")
        return None, borrower_entity_id

    raise ValueError("Provide borrower_person_id or borrower_entity_id")


async def list_liability_types(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """SELECT code, name, description, created_at
           FROM liability_types
           ORDER BY code"""
    )
    return _rows_to_list(rows)



# upsert_party_ref and list_party_refs removed — party_refs table eliminated
# in stewardos_db consolidation. Liabilities now use direct borrower_person_id
# / borrower_entity_id FKs to core.people / core.entities.


async def upsert_liability(
    pool: asyncpg.Pool,
    *,
    name: str,
    liability_type_code: str,
    outstanding_principal: float,
    currency: str,
    liability_id: int | None = None,
    borrower_person_id: int | None = None,
    borrower_entity_id: int | None = None,
    jurisdiction_code: str | None = None,
    collateral_asset_id: int | None = None,
    lender_name: str | None = None,
    account_number_last4: str | None = None,
    origination_date: str | None = None,
    maturity_date: str | None = None,
    original_principal: float | None = None,
    credit_limit: float | None = None,
    rate_type: str = "fixed",
    rate_index: str | None = None,
    interest_rate: float | None = None,
    rate_spread_bps: float | None = None,
    amortization_months: int | None = None,
    remaining_term_months: int | None = None,
    payment_frequency: str = "monthly",
    scheduled_payment: float | None = None,
    escrow_payment: float | None = None,
    next_payment_date: str | None = None,
    prepayment_penalty: float | None = None,
    status: str = "active",
    metadata: dict | str | None = None,
) -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        return _error_response("name is required", code="validation_error")

    normalized_currency = _normalize_currency_code(currency)
    if not normalized_currency:
        return _error_response("currency must be a valid ISO-4217 code", code="validation_error")

    liability_type_exists = await pool.fetchval(
        "SELECT 1 FROM liability_types WHERE code = $1",
        liability_type_code,
    )
    if not liability_type_exists:
        valid_rows = await pool.fetch("SELECT code FROM liability_types ORDER BY code")
        valid_codes = [r["code"] for r in valid_rows]
        return _error_response(
            f"Unknown liability_type_code '{liability_type_code}'",
            code="validation_error",
            payload={"valid_codes": valid_codes},
        )

    jurisdiction_id = None
    if jurisdiction_code:
        jurisdiction_id = await pool.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            jurisdiction_code,
        )
        if jurisdiction_id is None:
            return _error_response(f"Unknown jurisdiction_code: {jurisdiction_code}", code="validation_error")

    try:
        normalized_payment_frequency = _normalize_payment_frequency(payment_frequency)
        od = _parse_iso_date(origination_date, "origination_date")
        md = _parse_iso_date(maturity_date, "maturity_date")
        nd = _parse_iso_date(next_payment_date, "next_payment_date")
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")

    payload = _coerce_json_input(metadata)
    async with pool.acquire() as conn:
        async with conn.transaction():
            resolved_person_id, resolved_entity_id = await _resolve_borrower(
                pool=conn,
                borrower_person_id=borrower_person_id,
                borrower_entity_id=borrower_entity_id,
            )

            if liability_id:
                updated = await conn.fetchrow(
                    """UPDATE finance.liabilities
                       SET name=$1,
                           liability_type_code=$2,
                           jurisdiction_id=$3,
                           borrower_person_id=$4,
                           borrower_entity_id=$5,
                           collateral_asset_id=$6,
                           lender_name=$7,
                           account_number_last4=$8,
                           currency=$9,
                           origination_date=$10,
                           maturity_date=$11,
                           original_principal=$12,
                           outstanding_principal=$13,
                           credit_limit=$14,
                           rate_type=$15,
                           rate_index=$16,
                           interest_rate=$17,
                           rate_spread_bps=$18,
                           amortization_months=$19,
                           remaining_term_months=$20,
                           payment_frequency=$21,
                           scheduled_payment=$22,
                           escrow_payment=$23,
                           next_payment_date=$24,
                           prepayment_penalty=$25,
                           status=$26,
                           metadata=$27::jsonb,
                           updated_at=now()
                       WHERE id=$28
                       RETURNING id""",
                    clean_name,
                    liability_type_code,
                    jurisdiction_id,
                    resolved_person_id,
                    resolved_entity_id,
                    collateral_asset_id,
                    lender_name,
                    account_number_last4,
                    normalized_currency,
                    od,
                    md,
                    original_principal,
                    outstanding_principal,
                    credit_limit,
                    rate_type,
                    rate_index,
                    interest_rate,
                    rate_spread_bps,
                    amortization_months,
                    remaining_term_months,
                    normalized_payment_frequency,
                    scheduled_payment,
                    escrow_payment,
                    nd,
                    prepayment_penalty,
                    status,
                    json.dumps(payload),
                    liability_id,
                )
                if updated is None:
                    return _error_response(f"liability_id {liability_id} not found", code="not_found")
                target_id = int(updated["id"])
            else:
                created = await conn.fetchrow(
                    """INSERT INTO finance.liabilities (
                           name, liability_type_code, jurisdiction_id, borrower_person_id, borrower_entity_id,
                           collateral_asset_id, lender_name, account_number_last4, currency,
                           origination_date, maturity_date, original_principal, outstanding_principal,
                           credit_limit, rate_type, rate_index, interest_rate, rate_spread_bps,
                           amortization_months, remaining_term_months, payment_frequency, scheduled_payment,
                           escrow_payment, next_payment_date, prepayment_penalty, status, metadata
                       ) VALUES (
                           $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
                           $20,$21,$22,$23,$24,$25,$26,$27::jsonb
                       )
                       RETURNING id""",
                    clean_name,
                    liability_type_code,
                    jurisdiction_id,
                    resolved_person_id,
                    resolved_entity_id,
                    collateral_asset_id,
                    lender_name,
                    account_number_last4,
                    normalized_currency,
                    od,
                    md,
                    original_principal,
                    outstanding_principal,
                    credit_limit,
                    rate_type,
                    rate_index,
                    interest_rate,
                    rate_spread_bps,
                    amortization_months,
                    remaining_term_months,
                    normalized_payment_frequency,
                    scheduled_payment,
                    escrow_payment,
                    nd,
                    prepayment_penalty,
                    status,
                    json.dumps(payload),
                )
                target_id = int(created["id"])

            row = await conn.fetchrow(
                """SELECT l.*, j.code AS jurisdiction_code, j.name AS jurisdiction_name,
                          COALESCE(bp.legal_name, be.name) AS borrower_name,
                          CASE WHEN l.borrower_person_id IS NOT NULL THEN 'person' ELSE 'entity' END AS borrower_type
                   FROM finance.liabilities l
                   LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
                   LEFT JOIN people bp ON l.borrower_person_id = bp.id
                   LEFT JOIN entities be ON l.borrower_entity_id = be.id
                   WHERE l.id = $1""",
                target_id,
            )
    return _row_to_dict(row)


async def list_liabilities(
    pool: asyncpg.Pool,
    *,
    status: str | None = None,
    borrower_person_id: int | None = None,
    borrower_entity_id: int | None = None,
    collateral_asset_id: int | None = None,
    jurisdiction_code: str | None = None,
    limit: int = 500,
) -> list[dict]:
    cap = max(1, min(limit, 5000))
    clauses: list[str] = []
    params: list = []

    if status:
        params.append(status)
        clauses.append(f"l.status = ${len(params)}")
    if borrower_person_id is not None:
        params.append(borrower_person_id)
        clauses.append(f"l.borrower_person_id = ${len(params)}")
    if borrower_entity_id is not None:
        params.append(borrower_entity_id)
        clauses.append(f"l.borrower_entity_id = ${len(params)}")
    if collateral_asset_id is not None:
        params.append(collateral_asset_id)
        clauses.append(f"l.collateral_asset_id = ${len(params)}")
    if jurisdiction_code:
        params.append(jurisdiction_code)
        clauses.append(f"j.code = ${len(params)}")

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    params.append(cap)
    rows = await pool.fetch(
        f"""SELECT l.*, j.code AS jurisdiction_code, j.name AS jurisdiction_name,
                   COALESCE(bp.legal_name, be.name) AS borrower_name,
                   CASE WHEN l.borrower_person_id IS NOT NULL THEN 'person' ELSE 'entity' END AS borrower_type
            FROM finance.liabilities l
            LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
            LEFT JOIN people bp ON l.borrower_person_id = bp.id
            LEFT JOIN entities be ON l.borrower_entity_id = be.id
            {where_sql}
            ORDER BY l.updated_at DESC, l.id DESC
            LIMIT ${len(params)}""",
        *params,
    )
    return _rows_to_list(rows)


async def record_liability_rate_reset(
    pool: asyncpg.Pool,
    *,
    liability_id: int,
    effective_date: str,
    rate_type: str,
    interest_rate: float,
    rate_index: str | None = None,
    rate_spread_bps: float | None = None,
    cap_rate: float | None = None,
    floor_rate: float | None = None,
    reset_frequency_months: int | None = None,
    notes: str | None = None,
    metadata: dict | str | None = None,
) -> dict:
    try:
        as_of = _parse_iso_date(effective_date, "effective_date")
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")
    assert as_of is not None

    payload = _coerce_json_input(metadata)
    async with pool.acquire() as conn:
        async with conn.transaction():
            liability_exists = await conn.fetchval("SELECT 1 FROM liabilities WHERE id = $1", liability_id)
            if not liability_exists:
                return _error_response(f"liability_id {liability_id} not found", code="not_found")

            row = await conn.fetchrow(
                """INSERT INTO liability_rate_terms (
                       liability_id, effective_date, rate_type, rate_index, interest_rate,
                       rate_spread_bps, cap_rate, floor_rate, reset_frequency_months, notes, metadata
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
                   ON CONFLICT (liability_id, effective_date) DO UPDATE SET
                       rate_type = EXCLUDED.rate_type,
                       rate_index = EXCLUDED.rate_index,
                       interest_rate = EXCLUDED.interest_rate,
                       rate_spread_bps = EXCLUDED.rate_spread_bps,
                       cap_rate = EXCLUDED.cap_rate,
                       floor_rate = EXCLUDED.floor_rate,
                       reset_frequency_months = EXCLUDED.reset_frequency_months,
                       notes = EXCLUDED.notes,
                       metadata = EXCLUDED.metadata
                   RETURNING *""",
                liability_id,
                as_of,
                rate_type,
                rate_index,
                interest_rate,
                rate_spread_bps,
                cap_rate,
                floor_rate,
                reset_frequency_months,
                notes,
                json.dumps(payload),
            )

            await conn.execute(
                """UPDATE liabilities
                   SET rate_type = $1,
                       rate_index = $2,
                       interest_rate = $3,
                       rate_spread_bps = $4,
                       updated_at = now()
                   WHERE id = $5""",
                rate_type,
                rate_index,
                interest_rate,
                rate_spread_bps,
                liability_id,
            )

    return _row_to_dict(row)


async def record_liability_payment(
    pool: asyncpg.Pool,
    *,
    liability_id: int,
    payment_date: str,
    amount_total: float,
    amount_principal: float | None = None,
    amount_interest: float | None = None,
    amount_escrow: float | None = None,
    idempotency_key: str | None = None,
    source: str = "manual",
    reference: str | None = None,
    metadata: dict | str | None = None,
) -> dict:
    try:
        pd = _parse_iso_date(payment_date, "payment_date")
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")
    assert pd is not None

    async with pool.acquire() as conn:
        async with conn.transaction():
            liability = await conn.fetchrow("SELECT * FROM liabilities WHERE id = $1", liability_id)
            if liability is None:
                return _error_response(f"liability_id {liability_id} not found", code="not_found")

            try:
                payment_frequency = _normalize_payment_frequency(liability["payment_frequency"])
                principal_component, amount_interest, amount_escrow = _validate_payment_split(
                    amount_total=amount_total,
                    amount_principal=amount_principal,
                    amount_interest=amount_interest,
                    amount_escrow=amount_escrow,
                )
            except ValueError as exc:
                return _error_response(str(exc), code="validation_error")

            resolved_idempotency_key = (idempotency_key or "").strip() or _derived_payment_idempotency_key(
                liability_id=liability_id,
                payment_date=pd,
                amount_total=amount_total,
                amount_principal=principal_component,
                amount_interest=amount_interest,
                amount_escrow=amount_escrow,
                source=source,
                reference=reference,
            )

            existing_payment = await conn.fetchrow(
                """SELECT id, liability_id, payment_date, amount_total, amount_principal,
                          amount_interest, amount_escrow, idempotency_key
                   FROM liability_payments
                   WHERE idempotency_key = $1""",
                resolved_idempotency_key,
            )
            if existing_payment is not None:
                current_liability = await conn.fetchrow(
                    "SELECT outstanding_principal, status, next_payment_date FROM liabilities WHERE id = $1",
                    liability_id,
                )
                return {
                    "payment": _row_to_dict(existing_payment),
                    "liability_id": liability_id,
                    "updated_outstanding_principal": float(current_liability["outstanding_principal"] or 0.0),
                    "updated_status": current_liability["status"],
                    "next_payment_date": (
                        current_liability["next_payment_date"].isoformat()
                        if isinstance(current_liability["next_payment_date"], date)
                        else None
                    ),
                    "idempotency_key": resolved_idempotency_key,
                    "idempotency_reused": True,
                }

            outstanding = float(liability["outstanding_principal"] or 0.0)
            if principal_component - outstanding > 0.005:
                return _error_response(
                    "amount_principal cannot exceed outstanding_principal",
                    code="validation_error",
                )
            new_outstanding = max(0.0, outstanding - principal_component)
            new_status = "paid_off" if new_outstanding <= 0.005 else liability["status"]

            next_date = _advance_next_payment_date(
                liability["next_payment_date"],
                payment_date=pd,
                payment_frequency=payment_frequency,
            )

            payment_row = await conn.fetchrow(
                """INSERT INTO liability_payments (
                       liability_id, payment_date, amount_total, amount_principal,
                       amount_interest, amount_escrow, idempotency_key, source, reference, metadata
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
                   RETURNING *""",
                liability_id,
                pd,
                amount_total,
                principal_component,
                amount_interest,
                amount_escrow,
                resolved_idempotency_key,
                source,
                reference,
                json.dumps(_coerce_json_input(metadata)),
            )

            await conn.execute(
                """UPDATE liabilities
                   SET outstanding_principal = $1,
                       status = $2,
                       next_payment_date = $3,
                       updated_at = now()
                   WHERE id = $4""",
                new_outstanding,
                new_status,
                next_date,
                liability_id,
            )

    return {
        "payment": _row_to_dict(payment_row),
        "liability_id": liability_id,
        "updated_outstanding_principal": new_outstanding,
        "updated_status": new_status,
        "next_payment_date": next_date.isoformat() if isinstance(next_date, date) else None,
        "idempotency_key": resolved_idempotency_key,
        "idempotency_reused": False,
    }


async def generate_liability_amortization(
    pool: asyncpg.Pool,
    *,
    liability_id: int,
    scenario_tag: str = "base",
    months: int | None = None,
    annual_rate_override: float | None = None,
    payment_total_override: float | None = None,
    escrow_payment_override: float | None = None,
    start_date: str | None = None,
) -> dict:
    liability = await pool.fetchrow("SELECT * FROM liabilities WHERE id = $1", liability_id)
    if liability is None:
        return _error_response(f"liability_id {liability_id} not found", code="not_found")

    try:
        schedule_payload = _build_amortization_payload(
            liability=liability,
            months=months,
            annual_rate_override=annual_rate_override,
            payment_total_override=payment_total_override,
            escrow_payment_override=escrow_payment_override,
            start_date=start_date,
        )
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")

    async with pool.acquire() as conn:
        async with conn.transaction():
            await _persist_amortization_schedule(
                conn,
                liability_id=liability_id,
                scenario_tag=scenario_tag,
                schedule=schedule_payload["schedule"],
                annual_rate=schedule_payload["annual_rate"],
                term_months=schedule_payload["term_months"],
            )

    return _ok_response(
        {
            "liability_id": liability_id,
            "scenario_tag": scenario_tag,
            "schedule_points": len(schedule_payload["schedule"]),
            "term_months": schedule_payload["term_months"],
            "annual_rate": schedule_payload["annual_rate"],
            "payment_total": schedule_payload["payment_total"],
            "total_payments": schedule_payload["total_payments"],
            "total_interest": schedule_payload["total_interest"],
            "ending_balance": schedule_payload["ending_balance"],
        }
    )


async def record_refinance_offer(
    pool: asyncpg.Pool,
    *,
    liability_id: int,
    offer_date: str,
    offered_rate: float,
    offered_term_months: int,
    lender_name: str | None = None,
    product_type: str = "rate_term_refi",
    rate_type: str = "fixed",
    offered_principal: float | None = None,
    points_cost: float = 0.0,
    lender_fees: float = 0.0,
    third_party_fees: float = 0.0,
    prepayment_penalty_cost: float = 0.0,
    cash_out_amount: float = 0.0,
    metadata: dict | str | None = None,
) -> dict:
    liability_exists = await pool.fetchval("SELECT 1 FROM liabilities WHERE id = $1", liability_id)
    if not liability_exists:
        return _error_response(f"liability_id {liability_id} not found", code="not_found")
    try:
        od = _parse_iso_date(offer_date, "offer_date")
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")
    assert od is not None

    row = await pool.fetchrow(
        """INSERT INTO refinance_offers (
               liability_id, offer_date, lender_name, product_type, offered_rate, rate_type,
               offered_term_months, offered_principal, points_cost, lender_fees, third_party_fees,
               prepayment_penalty_cost, cash_out_amount, metadata
           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
           RETURNING *""",
        liability_id,
        od,
        lender_name,
        product_type,
        offered_rate,
        rate_type,
        offered_term_months,
        offered_principal,
        points_cost,
        lender_fees,
        third_party_fees,
        prepayment_penalty_cost,
        cash_out_amount,
        json.dumps(_coerce_json_input(metadata)),
    )
    return _ok_response(_row_to_dict(row) or {})


async def analyze_refinance_npv(
    pool: asyncpg.Pool,
    *,
    liability_id: int,
    refinance_offer_id: int,
    discount_rate_annual: float = 0.05,
) -> dict:
    liability = await pool.fetchrow("SELECT * FROM liabilities WHERE id = $1", liability_id)
    if liability is None:
        return _error_response(f"liability_id {liability_id} not found", code="not_found")
    offer = await pool.fetchrow(
        """SELECT * FROM refinance_offers
           WHERE id = $1 AND liability_id = $2""",
        refinance_offer_id,
        liability_id,
    )
    if offer is None:
        return _error_response(
            f"refinance_offer_id {refinance_offer_id} not found for liability_id {liability_id}",
            code="not_found",
        )

    metrics = _compute_refi_metrics(
        liability_row=liability,
        offer_row=offer,
        discount_rate_annual=discount_rate_annual,
        projection_inputs=await _load_liability_projection_inputs(pool=pool, liability_row=liability),
    )

    run_row = await pool.fetchrow(
        """INSERT INTO liability_analytics_runs (
               liability_id, refinance_offer_id, run_type, run_date,
               recommendation, npv_savings, break_even_months, annual_payment_change,
               assumptions, outputs
           ) VALUES ($1,$2,'refinance_npv',$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb)
           RETURNING id""",
        liability_id,
        refinance_offer_id,
        date.today(),
        metrics["recommendation"],
        metrics["npv_savings"],
        metrics["break_even_months"],
        metrics["annual_payment_change"],
        json.dumps({"discount_rate_annual": discount_rate_annual}),
        json.dumps(metrics),
    )

    return _ok_response(
        {
            "analytics_run_id": int(run_row["id"]),
            "liability_id": liability_id,
            "refinance_offer_id": refinance_offer_id,
            **metrics,
        },
        model_quality=metrics.get("model_quality"),
    )


async def analyze_heloc_economics(
    pool: asyncpg.Pool,
    *,
    liability_id: int,
    draw_amount: float,
    draw_term_months: int,
    heloc_rate: float,
    alternative_rate: float | None = None,
    discount_rate_annual: float = 0.05,
    origination_cost: float = 0.0,
) -> dict:
    liability = await pool.fetchrow("SELECT * FROM liabilities WHERE id = $1", liability_id)
    if liability is None:
        return _error_response(f"liability_id {liability_id} not found", code="not_found")

    if draw_amount <= 0:
        return _error_response("draw_amount must be > 0", code="validation_error")
    if draw_term_months <= 0:
        return _error_response("draw_term_months must be > 0", code="validation_error")

    alt_rate = alternative_rate
    projection_inputs = await _load_liability_projection_inputs(pool=pool, liability_row=liability)
    assumptions_used = list(projection_inputs["assumptions_used"])
    if alt_rate is None:
        alt_rate, alt_rate_assumptions = _projected_alternative_rate(
            liability_row=liability,
            draw_term_months=draw_term_months,
            projection_inputs=projection_inputs,
        )
        assumptions_used.extend(alt_rate_assumptions)
    else:
        assumptions_used.append("Used caller-provided alternative_rate override")

    heloc_payment = _monthly_payment(draw_amount, heloc_rate, draw_term_months)
    alt_payment = _monthly_payment(draw_amount, alt_rate, draw_term_months)
    heloc_interest_total = (heloc_payment * draw_term_months) - draw_amount
    alt_interest_total = (alt_payment * draw_term_months) - draw_amount

    pv_heloc = _pv_amounts([heloc_payment] * draw_term_months, discount_rate_annual) + max(0.0, origination_cost)
    pv_alt = _pv_amounts([alt_payment] * draw_term_months, discount_rate_annual)
    npv_savings = pv_alt - pv_heloc

    recommendation = "recommend" if npv_savings > 0 else "hold"
    annual_payment_change = (heloc_payment - alt_payment) * 12.0

    outputs = {
        "draw_amount": draw_amount,
        "draw_term_months": draw_term_months,
        "heloc_rate": heloc_rate,
        "alternative_rate": alt_rate,
        "heloc_monthly_payment": heloc_payment,
        "alternative_monthly_payment": alt_payment,
        "heloc_interest_total": heloc_interest_total,
        "alternative_interest_total": alt_interest_total,
        "pv_heloc_total": pv_heloc,
        "pv_alternative_total": pv_alt,
        "npv_savings": npv_savings,
        "annual_payment_change": annual_payment_change,
        "recommendation": recommendation,
        "model_quality": projection_inputs["model_quality"],
        "assumptions_used": assumptions_used,
    }

    run_row = await pool.fetchrow(
        """INSERT INTO liability_analytics_runs (
               liability_id, run_type, run_date, recommendation,
               npv_savings, annual_payment_change, assumptions, outputs
           ) VALUES ($1,'heloc_economics',$2,$3,$4,$5,$6::jsonb,$7::jsonb)
           RETURNING id""",
        liability_id,
        date.today(),
        recommendation,
        npv_savings,
        annual_payment_change,
        json.dumps(
            {
                "discount_rate_annual": discount_rate_annual,
                "origination_cost": origination_cost,
            }
        ),
        json.dumps(outputs),
    )

    return _ok_response(
        {
            "analytics_run_id": int(run_row["id"]),
            "liability_id": liability_id,
            **outputs,
        },
        model_quality=projection_inputs["model_quality"],
    )


async def get_refi_opportunities(
    pool: asyncpg.Pool,
    *,
    min_npv_savings: float = 0.0,
    max_break_even_months: float = 36.0,
    discount_rate_annual: float = 0.05,
    include_hold: bool = False,
) -> dict:
    liabilities = await pool.fetch(
        """SELECT l.*,
                  COALESCE(bp.legal_name, be.name) AS borrower_name,
                  j.code AS jurisdiction_code
           FROM finance.liabilities l
           LEFT JOIN people bp ON l.borrower_person_id = bp.id
           LEFT JOIN entities be ON l.borrower_entity_id = be.id
           LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
           WHERE l.status = 'active'
           ORDER BY l.id"""
    )

    opportunities: list[dict] = []
    for liability in liabilities:
        offer = await pool.fetchrow(
            """SELECT * FROM refinance_offers
               WHERE liability_id = $1
               ORDER BY offer_date DESC, id DESC
               LIMIT 1""",
            liability["id"],
        )
        if offer is None:
            continue

        metrics = _compute_refi_metrics(
            liability_row=liability,
            offer_row=offer,
            discount_rate_annual=discount_rate_annual,
            projection_inputs=await _load_liability_projection_inputs(pool=pool, liability_row=liability),
        )
        should_include = (
            metrics["npv_savings"] >= min_npv_savings
            and (
                metrics["break_even_months"] is None
                or metrics["break_even_months"] <= max_break_even_months
            )
        )
        if not include_hold and metrics["recommendation"] == "hold":
            should_include = False

        if should_include:
            opportunities.append(
                {
                    "liability_id": liability["id"],
                    "liability_name": liability["name"],
                    "liability_type_code": liability["liability_type_code"],
                    "borrower_name": liability["borrower_name"],
                    "jurisdiction_code": liability["jurisdiction_code"],
                    "outstanding_principal": float(liability["outstanding_principal"] or 0.0),
                    "current_rate": _float_or_none(liability["interest_rate"]),
                    "offer_id": offer["id"],
                    "offer_date": offer["offer_date"].isoformat() if isinstance(offer["offer_date"], date) else None,
                    "offered_rate": _float_or_none(offer["offered_rate"]),
                    **metrics,
                }
            )

    opportunities.sort(key=lambda item: float(item["npv_savings"]), reverse=True)
    return _ok_response(opportunities)


async def get_liability_summary(
    pool: asyncpg.Pool,
    *,
    status: str = "active",
    jurisdiction: str | None = None,
    borrower_person_id: int | None = None,
    borrower_entity_id: int | None = None,
) -> dict:
    clauses: list[str] = ["l.status = $1"]
    params: list = [status]

    if jurisdiction:
        params.append(jurisdiction)
        clauses.append(f"j.code = ${len(params)}")
    if borrower_person_id is not None:
        params.append(borrower_person_id)
        clauses.append(f"l.borrower_person_id = ${len(params)}")
    if borrower_entity_id is not None:
        params.append(borrower_entity_id)
        clauses.append(f"l.borrower_entity_id = ${len(params)}")

    where_sql = " AND ".join(clauses)
    rows = await pool.fetch(
        f"""SELECT l.*,
                   j.code AS jurisdiction_code,
                   COALESCE(bp.legal_name, be.name) AS borrower_name
            FROM finance.liabilities l
            LEFT JOIN jurisdictions j ON l.jurisdiction_id = j.id
            LEFT JOIN people bp ON l.borrower_person_id = bp.id
            LEFT JOIN entities be ON l.borrower_entity_id = be.id
            WHERE {where_sql}
            ORDER BY l.outstanding_principal DESC NULLS LAST""",
        *params,
    )

    by_currency: dict[str, dict] = {}
    weighted_numerator = 0.0
    weighted_denominator = 0.0
    for row in rows:
        rec = _row_to_dict(row)
        currency = str(rec.get("currency") or "USD")
        outstanding = float(rec.get("outstanding_principal") or 0.0)
        interest_rate = _float_or_none(rec.get("interest_rate"))

        if currency not in by_currency:
            by_currency[currency] = {
                "currency": currency,
                "outstanding_principal_total": 0.0,
                "liability_count": 0,
            }
        by_currency[currency]["outstanding_principal_total"] += outstanding
        by_currency[currency]["liability_count"] += 1

        if interest_rate is not None:
            weighted_numerator += outstanding * interest_rate
            weighted_denominator += outstanding

    weighted_avg_interest = None
    if weighted_denominator > 0:
        weighted_avg_interest = weighted_numerator / weighted_denominator

    return {
        "status_filter": status,
        "jurisdiction_filter": jurisdiction,
        "borrower_person_id_filter": borrower_person_id,
        "borrower_entity_id_filter": borrower_entity_id,
        "liability_count": len(rows),
        "weighted_avg_interest_rate": weighted_avg_interest,
        "totals_by_currency": list(by_currency.values()),
        "liabilities": _rows_to_list(rows),
    }
