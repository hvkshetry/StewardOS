"""Safe-harbor planning and distribution comparison tools."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from stewardos_lib.response_ops import make_enveloped_tool

from errors import UnsupportedExactCase, error_response_for_exact_case
from models import as_date, parse_fiduciary_facts, parse_individual_facts
from returns import (
    _fiduciary_return_breakdown,
    _individual_return_breakdown,
    _money,
    _serialize,
)
from store import durability_mode, new_id, now_iso, persist_plan
from tax_config import (
    FEDERAL_ANNUALIZATION_FACTORS,
    FEDERAL_ANNUALIZED_CUMULATIVE_PERCENTAGES,
    AUTHORITY_BUNDLE_VERSIONS,
    FEDERAL_ESTIMATED_TAX_TRIGGER,
    FEDERAL_INSTALLMENT_DUE_DATES,
    FEDERAL_PRIOR_YEAR_HIGH_AGI_RATIO,
    FEDERAL_PRIOR_YEAR_HIGH_AGI_THRESHOLD,
    FEDERAL_PRIOR_YEAR_STANDARD_RATIO,
    FEDERAL_REQUIRED_PAYMENT_RATIO,
    MA_ESTIMATED_TAX_TRIGGER,
    MA_ANNUALIZED_CUMULATIVE_PERCENTAGES,
    MA_INSTALLMENT_DUE_DATES,
    MA_REGULAR_CUMULATIVE_PERCENTAGES,
    MA_REQUIRED_PAYMENT_RATIO,
    ZERO,
)


def _money_str(value: Decimal) -> str:
    return f"{_money(value):.2f}"


def _due_dates(raw_dates: tuple[str, ...]) -> list[date]:
    return [date.fromisoformat(value) for value in raw_dates]


def _split_equal(total: Decimal, count: int) -> list[Decimal]:
    if count <= 0 or total <= ZERO:
        return []
    per = (total / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    items = [per for _ in range(count)]
    delta = total - sum(items)
    if items:
        items[-1] = _money(items[-1] + delta)
    return [_money(item) for item in items]


def _regular_cumulative_percentages(count: int) -> tuple[Decimal, ...]:
    if count <= 0:
        return ()
    step = Decimal("1") / Decimal(count)
    return tuple(step * Decimal(idx + 1) for idx in range(count))


def _estimated_buckets(events, due_dates: list[date], jurisdiction: str) -> list[Decimal]:
    buckets = [ZERO for _ in due_dates]
    for event in events:
        if event.jurisdiction != jurisdiction:
            continue
        for idx, due_date in enumerate(due_dates):
            if event.payment_date <= due_date:
                buckets[idx] += event.amount
                break
    return [_money(item) for item in buckets]


def _withholding_ratable_buckets(events, due_dates: list[date], jurisdiction: str) -> list[Decimal]:
    buckets = [ZERO for _ in due_dates]
    for event in events:
        if event.jurisdiction != jurisdiction:
            continue
        if event.treat_as_ratable:
            shares = _split_equal(event.amount, len(due_dates))
            for idx, share in enumerate(shares):
                buckets[idx] += share
        else:
            for idx, due_date in enumerate(due_dates):
                if event.payment_date <= due_date:
                    buckets[idx] += event.amount
                    break
    return [_money(item) for item in buckets]


def _cumulative(items: list[Decimal]) -> list[Decimal]:
    running = ZERO
    out: list[Decimal] = []
    for item in items:
        running += item
        out.append(_money(running))
    return out


def _required_payment(current_tax: Decimal, prior_year, *, current_ratio: Decimal) -> Decimal:
    if current_tax <= ZERO:
        return ZERO
    if prior_year is None:
        return _money(current_tax * current_ratio)
    if not prior_year.filed or not prior_year.full_year_return:
        return _money(current_tax * current_ratio)
    prior_ratio = (
        FEDERAL_PRIOR_YEAR_HIGH_AGI_RATIO
        if prior_year.adjusted_gross_income > FEDERAL_PRIOR_YEAR_HIGH_AGI_THRESHOLD
        else FEDERAL_PRIOR_YEAR_STANDARD_RATIO
    )
    return _money(min(current_tax * current_ratio, prior_year.total_tax * prior_ratio))


def _required_massachusetts_payment(current_tax: Decimal, *, trigger: Decimal) -> Decimal:
    if current_tax <= trigger:
        return ZERO
    return _money(current_tax * MA_REQUIRED_PAYMENT_RATIO)


def _scale_massachusetts_individual(base, factor: Decimal):
    if base is None:
        return None
    return replace(
        base,
        taxable_general_income=_money(base.taxable_general_income * factor),
        taxable_short_term_capital_gains=_money(base.taxable_short_term_capital_gains * factor),
        surtax_base=_money(base.surtax_base * factor) if base.surtax_base is not None else None,
    )


def _scale_massachusetts_fiduciary(base, factor: Decimal):
    if base is None:
        return None
    return replace(
        base,
        taxable_general_income=_money(base.taxable_general_income * factor),
        taxable_short_term_capital_gains=_money(base.taxable_short_term_capital_gains * factor),
        surtax_base=_money(base.surtax_base * factor) if base.surtax_base is not None else None,
    )


def _individual_annualized_taxes(facts) -> dict[str, list[dict[str, Any]]] | None:
    if not facts.annualized_periods:
        return None

    profiles: list[dict[str, Any]] = []
    for idx, period in enumerate(facts.annualized_periods):
        factor = FEDERAL_ANNUALIZATION_FACTORS[idx]
        annualized_facts = replace(
            facts,
            wages=_money(period.wages * factor),
            taxable_interest=_money(period.taxable_interest * factor),
            ordinary_dividends=_money(period.ordinary_dividends * factor),
            qualified_dividends=_money(period.qualified_dividends * factor),
            short_term_capital_gains=_money(period.short_term_capital_gains * factor),
            long_term_capital_gains=_money(period.long_term_capital_gains * factor),
            other_ordinary_income=_money(period.other_ordinary_income * factor),
            above_line_deductions=_money(period.above_line_deductions * factor),
            withholding_events=(),
            estimated_payments=(),
            annualized_periods=(),
            massachusetts=_scale_massachusetts_individual(period.massachusetts, factor),
        )
        breakdown = _individual_return_breakdown(annualized_facts)
        profiles.append(
            {
                "period_end": period.period_end.isoformat(),
                "annualization_factor": factor,
                "federal_current_tax": breakdown["federal"]["total_tax"],
                "massachusetts_current_tax": breakdown["massachusetts"]["total_tax"],
            }
        )
    return {"profiles": profiles}


def _fiduciary_annualized_taxes(facts) -> dict[str, list[dict[str, Any]]] | None:
    if not facts.annualized_periods:
        return None

    profiles: list[dict[str, Any]] = []
    for idx, period in enumerate(facts.annualized_periods):
        factor = FEDERAL_ANNUALIZATION_FACTORS[idx]
        annualized_facts = replace(
            facts,
            taxable_interest=_money(period.taxable_interest * factor),
            ordinary_dividends=_money(period.ordinary_dividends * factor),
            qualified_dividends=_money(period.qualified_dividends * factor),
            short_term_capital_gains=_money(period.short_term_capital_gains * factor),
            long_term_capital_gains=_money(period.long_term_capital_gains * factor),
            other_ordinary_income=_money(period.other_ordinary_income * factor),
            deductions=_money(period.deductions * factor),
            withholding_events=(),
            estimated_payments=(),
            annualized_periods=(),
            massachusetts=_scale_massachusetts_fiduciary(period.massachusetts, factor),
        )
        breakdown = _fiduciary_return_breakdown(annualized_facts)
        profiles.append(
            {
                "period_end": period.period_end.isoformat(),
                "annualization_factor": factor,
                "federal_current_tax": breakdown["federal"]["total_tax"],
                "massachusetts_current_tax": breakdown["massachusetts"]["total_tax"],
            }
        )
    return {"profiles": profiles}


def _jurisdiction_installments(
    *,
    current_tax: Decimal,
    required_payment: Decimal,
    trigger_met: bool,
    due_dates: list[date],
    estimates,
    withholdings,
    jurisdiction: str,
    as_of: date,
    regular_cumulative_percentages: tuple[Decimal, ...],
    annualized_cumulative_percentages: tuple[Decimal, ...] | None = None,
    annualized_current_taxes: list[Decimal] | None = None,
    prior_year_safe_harbor_available: bool = True,
    safe_harbor_rule: str | None = None,
) -> dict[str, Any]:
    estimate_buckets = _estimated_buckets(estimates, due_dates, jurisdiction)
    withholding_buckets = _withholding_ratable_buckets(withholdings, due_dates, jurisdiction)
    payment_buckets = [_money(estimate_buckets[idx] + withholding_buckets[idx]) for idx in range(len(due_dates))]
    paid_cumulative = _cumulative(payment_buckets)

    installments = []
    past_due_deficit = ZERO
    for idx, due_date in enumerate(due_dates):
        regular_required_cumulative = _money(required_payment * regular_cumulative_percentages[idx])
        annualized_required_cumulative = None
        required_basis = "regular_installment"
        required_cumulative = regular_required_cumulative
        if annualized_current_taxes is not None and annualized_cumulative_percentages is not None:
            annualized_required_cumulative = _money(
                annualized_current_taxes[idx] * annualized_cumulative_percentages[idx]
            )
            if annualized_required_cumulative < regular_required_cumulative:
                required_cumulative = annualized_required_cumulative
                required_basis = "annualized_income"
        underpayment = _money(max(ZERO, required_cumulative - paid_cumulative[idx]))
        if due_date < as_of:
            past_due_deficit += underpayment
        installment = {
            "due_date": due_date.isoformat(),
            "required_cumulative": required_cumulative,
            "paid_cumulative": paid_cumulative[idx],
            "underpayment": underpayment,
            "regular_required_cumulative": regular_required_cumulative,
            "required_basis": required_basis,
        }
        if annualized_required_cumulative is not None:
            installment["annualized_required_cumulative"] = annualized_required_cumulative
        installments.append(installment)

    total_paid = _money(sum(event.amount for event in estimates if event.jurisdiction == jurisdiction))
    total_paid += _money(sum(event.amount for event in withholdings if event.jurisdiction == jurisdiction))
    remaining_amount = _money(max(ZERO, required_payment - total_paid))
    remaining_due_dates = [due for due in due_dates if due >= as_of]

    return {
        "trigger_met": trigger_met,
        "current_tax": _money(current_tax),
        "required_annual_payment": required_payment,
        "installments": installments,
        "remaining_required_payment": remaining_amount,
        "remaining_due_dates": [due.isoformat() for due in remaining_due_dates],
        "past_due_deficit": _money(past_due_deficit),
        "prior_year_safe_harbor_available": prior_year_safe_harbor_available,
        "safe_harbor_rule": safe_harbor_rule or "regular_installment",
        "annualized_income_method_used": bool(annualized_current_taxes is not None),
    }


def _build_estimated_actions(
    *,
    jurisdiction: str,
    installments: list[dict[str, Any]],
    as_of: date,
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    additional_cumulative = ZERO
    for installment in installments:
        due_date = date.fromisoformat(installment["due_date"])
        if due_date < as_of:
            continue
        required_cumulative = Decimal(str(installment["required_cumulative"]))
        paid_cumulative = Decimal(str(installment["paid_cumulative"]))
        incremental_needed = _money(max(ZERO, required_cumulative - paid_cumulative - additional_cumulative))
        if incremental_needed <= ZERO:
            continue
        actions.append(
            {
                "action": "make_estimated_payment",
                "jurisdiction": jurisdiction,
                "due_date": due_date.isoformat(),
                "amount": _money_str(incremental_needed),
            }
        )
        additional_cumulative += incremental_needed
    return actions


def _build_withholding_actions(*, jurisdiction: str, remaining_amount: Decimal, as_of: date, tax_year: int) -> list[dict[str, str]]:
    if remaining_amount <= ZERO:
        return []
    return [
        {
            "action": "increase_withholding",
            "jurisdiction": jurisdiction,
            "deadline": max(as_of, date(tax_year, 12, 31)).isoformat(),
            "amount": _money_str(remaining_amount),
        }
    ]


def _individual_safe_harbor_state(facts, breakdown: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    tax_year = facts.tax_year
    federal_due_dates = FEDERAL_INSTALLMENT_DUE_DATES[tax_year]
    ma_due_dates = MA_INSTALLMENT_DUE_DATES[tax_year]

    federal_current_tax = breakdown["federal"]["total_tax"]
    federal_required = ZERO
    federal_trigger_met = (
        federal_current_tax - sum(event.amount for event in facts.withholding_events if event.jurisdiction == "US")
    ) > FEDERAL_ESTIMATED_TAX_TRIGGER
    if federal_trigger_met:
        federal_required = _required_payment(
            federal_current_tax,
            facts.prior_year,
            current_ratio=FEDERAL_REQUIRED_PAYMENT_RATIO,
        )

    ma_current_tax = breakdown["massachusetts"]["total_tax"]
    ma_trigger_met = (
        ma_current_tax - sum(event.amount for event in facts.withholding_events if event.jurisdiction == "MA")
    ) > MA_ESTIMATED_TAX_TRIGGER
    ma_required = _required_massachusetts_payment(ma_current_tax, trigger=MA_ESTIMATED_TAX_TRIGGER) if ma_trigger_met else ZERO
    annualized = _individual_annualized_taxes(facts)

    return {
        "federal": _jurisdiction_installments(
            current_tax=federal_current_tax,
            required_payment=federal_required,
            trigger_met=federal_trigger_met,
            due_dates=_due_dates(federal_due_dates),
            estimates=facts.estimated_payments,
            withholdings=facts.withholding_events,
            jurisdiction="US",
            as_of=as_of,
            regular_cumulative_percentages=_regular_cumulative_percentages(len(federal_due_dates)),
            annualized_cumulative_percentages=(
                FEDERAL_ANNUALIZED_CUMULATIVE_PERCENTAGES if annualized is not None else None
            ),
            annualized_current_taxes=(
                [row["federal_current_tax"] for row in annualized["profiles"]] if annualized is not None else None
            ),
            safe_harbor_rule="federal_required_annual_payment",
        ),
        "massachusetts": _jurisdiction_installments(
            current_tax=ma_current_tax,
            required_payment=ma_required,
            trigger_met=ma_trigger_met,
            due_dates=_due_dates(ma_due_dates),
            estimates=facts.estimated_payments,
            withholdings=facts.withholding_events,
            jurisdiction="MA",
            as_of=as_of,
            regular_cumulative_percentages=MA_REGULAR_CUMULATIVE_PERCENTAGES,
            annualized_cumulative_percentages=(
                MA_ANNUALIZED_CUMULATIVE_PERCENTAGES if annualized is not None else None
            ),
            annualized_current_taxes=(
                [row["massachusetts_current_tax"] for row in annualized["profiles"]] if annualized is not None else None
            ),
            safe_harbor_rule="massachusetts_80_percent_current_year",
        ),
        "annualized_income_method": _serialize(annualized["profiles"]) if annualized is not None else [],
    }


def _fiduciary_safe_harbor_state(facts, breakdown: dict[str, Any], *, as_of: date) -> dict[str, Any]:
    tax_year = facts.tax_year
    federal_due_dates = FEDERAL_INSTALLMENT_DUE_DATES[tax_year]
    ma_due_dates = MA_INSTALLMENT_DUE_DATES[tax_year]

    federal_current_tax = breakdown["federal"]["total_tax"]
    federal_required = ZERO
    federal_trigger_met = (
        federal_current_tax - sum(event.amount for event in facts.withholding_events if event.jurisdiction == "US")
    ) > FEDERAL_ESTIMATED_TAX_TRIGGER
    if federal_trigger_met:
        federal_required = _required_payment(
            federal_current_tax,
            facts.prior_year,
            current_ratio=FEDERAL_REQUIRED_PAYMENT_RATIO,
        )

    ma_current_tax = breakdown["massachusetts"]["total_tax"]
    ma_trigger_met = (
        ma_current_tax - sum(event.amount for event in facts.withholding_events if event.jurisdiction == "MA")
    ) > MA_ESTIMATED_TAX_TRIGGER
    ma_required = _required_massachusetts_payment(ma_current_tax, trigger=MA_ESTIMATED_TAX_TRIGGER) if ma_trigger_met else ZERO
    annualized = _fiduciary_annualized_taxes(facts)
    ma_first_year_fiduciary = bool(
        facts.prior_year and facts.prior_year.first_year_massachusetts_fiduciary
    )

    return {
        "federal": _jurisdiction_installments(
            current_tax=federal_current_tax,
            required_payment=federal_required,
            trigger_met=federal_trigger_met,
            due_dates=_due_dates(federal_due_dates),
            estimates=facts.estimated_payments,
            withholdings=facts.withholding_events,
            jurisdiction="US",
            as_of=as_of,
            regular_cumulative_percentages=_regular_cumulative_percentages(len(federal_due_dates)),
            annualized_cumulative_percentages=(
                FEDERAL_ANNUALIZED_CUMULATIVE_PERCENTAGES if annualized is not None else None
            ),
            annualized_current_taxes=(
                [row["federal_current_tax"] for row in annualized["profiles"]] if annualized is not None else None
            ),
            safe_harbor_rule="federal_required_annual_payment",
        ),
        "massachusetts": _jurisdiction_installments(
            current_tax=ma_current_tax,
            required_payment=ma_required,
            trigger_met=ma_trigger_met,
            due_dates=_due_dates(ma_due_dates),
            estimates=facts.estimated_payments,
            withholdings=facts.withholding_events,
            jurisdiction="MA",
            as_of=as_of,
            regular_cumulative_percentages=MA_REGULAR_CUMULATIVE_PERCENTAGES,
            annualized_cumulative_percentages=(
                MA_ANNUALIZED_CUMULATIVE_PERCENTAGES if annualized is not None else None
            ),
            annualized_current_taxes=(
                [row["massachusetts_current_tax"] for row in annualized["profiles"]] if annualized is not None else None
            ),
            prior_year_safe_harbor_available=not ma_first_year_fiduciary,
            safe_harbor_rule=(
                "massachusetts_80_percent_current_year_first_year_fiduciary"
                if ma_first_year_fiduciary
                else "massachusetts_80_percent_current_year"
            ),
        ),
        "annualized_income_method": _serialize(annualized["profiles"]) if annualized is not None else [],
    }


def _simulated_installment_status(
    state: dict[str, Any],
    *,
    additional_withholding_us: Decimal = ZERO,
    additional_withholding_ma: Decimal = ZERO,
) -> dict[str, bool]:
    def _jurisdiction_ok(payload: dict[str, Any], extra: Decimal) -> bool:
        if payload["required_annual_payment"] <= ZERO:
            return True
        if payload["past_due_deficit"] <= ZERO and extra == ZERO:
            return payload["remaining_required_payment"] <= ZERO
        required = payload["required_annual_payment"]
        paid = required - payload["remaining_required_payment"] + extra
        if paid < required:
            return False
        extra_cumulative = _cumulative(_split_equal(extra, len(payload["installments"]))) if extra > ZERO else []
        for idx, installment in enumerate(payload["installments"]):
            added = extra_cumulative[idx] if extra_cumulative else ZERO
            if Decimal(str(installment["paid_cumulative"])) + added < Decimal(str(installment["required_cumulative"])):
                return False
        return True

    return {
        "federal": _jurisdiction_ok(state["federal"], additional_withholding_us),
        "massachusetts": _jurisdiction_ok(state["massachusetts"], additional_withholding_ma),
    }


def compare_individual_payment_strategies_internal(
    facts: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    from readiness import assess_exact_support_internal

    assessment = assess_exact_support_internal("individual", facts)
    if not assessment["supported"]:
        raise UnsupportedExactCase(assessment["unsupported_reasons"])

    normalized = parse_individual_facts(facts)
    tax_year = normalized.tax_year
    as_of_date = as_date(as_of, field_name="as_of") if as_of else date(tax_year, 9, 30)
    breakdown = _individual_return_breakdown(normalized)
    state = _individual_safe_harbor_state(normalized, breakdown, as_of=as_of_date)

    estimated_actions = _build_estimated_actions(
        jurisdiction="US",
        installments=state["federal"]["installments"],
        as_of=as_of_date,
    ) + _build_estimated_actions(
        jurisdiction="MA",
        installments=state["massachusetts"]["installments"],
        as_of=as_of_date,
    )
    estimated_strategy = {
        "strategy_id": "estimated_payments",
        "additional_total": _money(
            state["federal"]["remaining_required_payment"] + state["massachusetts"]["remaining_required_payment"]
        ),
        "actions": estimated_actions,
        "installment_safe_harbor_satisfied": (
            state["federal"]["past_due_deficit"] <= ZERO
            and state["massachusetts"]["past_due_deficit"] <= ZERO
            and (
                state["federal"]["remaining_required_payment"] <= ZERO
                or bool(state["federal"]["remaining_due_dates"])
            )
            and (
                state["massachusetts"]["remaining_required_payment"] <= ZERO
                or bool(state["massachusetts"]["remaining_due_dates"])
            )
        ),
    }

    strategies = [estimated_strategy]
    can_adjust_withholding = normalized.wages > ZERO
    if can_adjust_withholding:
        withholding_us = state["federal"]["remaining_required_payment"]
        withholding_ma = state["massachusetts"]["remaining_required_payment"]
        withholding_status = _simulated_installment_status(
            state,
            additional_withholding_us=withholding_us,
            additional_withholding_ma=withholding_ma,
        )
        strategies.append(
            {
                "strategy_id": "ratable_withholding_catch_up",
                "additional_total": _money(withholding_us + withholding_ma),
                "actions": _build_withholding_actions(
                    jurisdiction="US",
                    remaining_amount=withholding_us,
                    as_of=as_of_date,
                    tax_year=tax_year,
                )
                + _build_withholding_actions(
                    jurisdiction="MA",
                    remaining_amount=withholding_ma,
                    as_of=as_of_date,
                    tax_year=tax_year,
                ),
                "installment_safe_harbor_satisfied": all(withholding_status.values()),
            }
        )

    strategies.sort(
        key=lambda row: (
            0 if row["installment_safe_harbor_satisfied"] else 1,
            0 if row["strategy_id"] == "ratable_withholding_catch_up" else 1,
            row["additional_total"],
        )
    )
    recommended = strategies[0]

    return {
        "comparison_id": new_id("pay_compare"),
        "entity_type": "individual",
        "tax_year": tax_year,
        "as_of": as_of_date.isoformat(),
        "projected_return": _serialize(breakdown),
        "safe_harbor": _serialize(state),
        "recommended_strategy": recommended["strategy_id"],
        "strategies": _serialize(strategies),
        "provenance": {
            "computed_at": now_iso(),
            "durability_mode": durability_mode(),
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
        },
    }


def plan_individual_safe_harbor_internal(
    facts: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    comparison = compare_individual_payment_strategies_internal(facts, as_of=as_of)
    plan_id = new_id("plan")
    tax_year = comparison["tax_year"]
    recommended = next(
        strategy for strategy in comparison["strategies"] if strategy["strategy_id"] == comparison["recommended_strategy"]
    )
    plan = {
        "plan_id": plan_id,
        "entity_type": "individual",
        "tax_year": tax_year,
        "as_of": comparison["as_of"],
        "projected_return": comparison["projected_return"],
        "safe_harbor": comparison["safe_harbor"],
        "recommended_strategy": comparison["recommended_strategy"],
        "recommended_actions": recommended["actions"],
        "provenance": comparison["provenance"],
    }
    persist_plan(
        {
            "plan_id": plan_id,
            "tool_name": "plan_individual_safe_harbor",
            "entity_type": "individual",
            "tax_year": tax_year,
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
            "facts": facts,
            "plan": plan,
        }
    )
    return plan


def plan_fiduciary_safe_harbor_internal(
    facts: dict[str, Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    from readiness import assess_exact_support_internal

    assessment = assess_exact_support_internal("fiduciary", facts)
    if not assessment["supported"]:
        raise UnsupportedExactCase(assessment["unsupported_reasons"])

    normalized = parse_fiduciary_facts(facts)
    tax_year = normalized.tax_year
    as_of_date = as_date(as_of, field_name="as_of") if as_of else date(tax_year, 9, 30)
    breakdown = _fiduciary_return_breakdown(normalized)
    state = _fiduciary_safe_harbor_state(normalized, breakdown, as_of=as_of_date)

    actions = _build_estimated_actions(
        jurisdiction="US",
        installments=state["federal"]["installments"],
        as_of=as_of_date,
    ) + _build_estimated_actions(
        jurisdiction="MA",
        installments=state["massachusetts"]["installments"],
        as_of=as_of_date,
    )
    plan_id = new_id("plan")
    plan = {
        "plan_id": plan_id,
        "entity_type": "fiduciary",
        "tax_year": tax_year,
        "as_of": as_of_date.isoformat(),
        "projected_return": _serialize(breakdown),
        "safe_harbor": _serialize(state),
        "recommended_strategy": "estimated_payments",
        "recommended_actions": actions,
        "massachusetts_first_year_fiduciary": bool(
            normalized.prior_year and normalized.prior_year.first_year_massachusetts_fiduciary
        ),
        "provenance": {
            "computed_at": now_iso(),
            "durability_mode": durability_mode(),
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
        },
    }
    persist_plan(
        {
            "plan_id": plan_id,
            "tool_name": "plan_fiduciary_safe_harbor",
            "entity_type": "fiduciary",
            "tax_year": tax_year,
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
            "facts": facts,
            "plan": plan,
        }
    )
    return plan


def compare_trust_distribution_strategies_internal(
    fiduciary_facts: dict[str, Any],
    beneficiary_facts: dict[str, Any],
    candidate_distribution_amounts: list[float | int | str],
) -> dict[str, Any]:
    from readiness import assess_exact_support_internal

    fiduciary_assessment = assess_exact_support_internal("fiduciary", fiduciary_facts)
    if not fiduciary_assessment["supported"]:
        raise UnsupportedExactCase(fiduciary_assessment["unsupported_reasons"])
    beneficiary_assessment = assess_exact_support_internal("individual", beneficiary_facts)
    if not beneficiary_assessment["supported"]:
        raise UnsupportedExactCase(beneficiary_assessment["unsupported_reasons"])

    fiduciary = parse_fiduciary_facts(fiduciary_facts)
    beneficiary = parse_individual_facts(beneficiary_facts)

    if fiduciary.tax_year != beneficiary.tax_year:
        raise ValueError(
            f"fiduciary_facts.tax_year ({fiduciary.tax_year}) must match "
            f"beneficiary_facts.tax_year ({beneficiary.tax_year})"
        )

    tax_year = fiduciary.tax_year
    beneficiary_base = _individual_return_breakdown(beneficiary)
    beneficiary_base_total = beneficiary_base["combined_total_tax"]

    options: list[dict[str, Any]] = []
    seen: set[Decimal] = set()
    for raw in candidate_distribution_amounts:
        amount = _money(Decimal(str(raw)))
        if amount in seen:
            continue
        seen.add(amount)

        trust_result = _fiduciary_return_breakdown(fiduciary, distribution_amount=amount)
        distributed = trust_result["federal"]["distributed_character"]
        beneficiary_with_distribution = replace(
            beneficiary,
            taxable_interest=beneficiary.taxable_interest + distributed.get("taxable_interest", ZERO),
            ordinary_dividends=beneficiary.ordinary_dividends + distributed.get("ordinary_dividends", ZERO),
            qualified_dividends=beneficiary.qualified_dividends + distributed.get("qualified_dividends", ZERO),
            long_term_capital_gains=beneficiary.long_term_capital_gains + distributed.get("long_term_capital_gains", ZERO),
            other_ordinary_income=beneficiary.other_ordinary_income + distributed.get("other_ordinary_income", ZERO),
        )
        beneficiary_result = _individual_return_breakdown(beneficiary_with_distribution)
        beneficiary_incremental_tax = _money(
            beneficiary_result["combined_total_tax"] - beneficiary_base_total
        )
        combined_incremental_tax = _money(
            trust_result["combined_total_tax"] + beneficiary_incremental_tax
        )
        options.append(
            {
                "distribution_amount": amount,
                "distributed_character": distributed,
                "trust_total_tax": trust_result["combined_total_tax"],
                "beneficiary_incremental_tax": beneficiary_incremental_tax,
                "combined_incremental_tax": combined_incremental_tax,
            }
        )

    if not options:
        raise ValueError("candidate_distribution_amounts must contain at least one amount")

    options.sort(key=lambda row: (row["combined_incremental_tax"], row["trust_total_tax"], row["distribution_amount"]))
    recommended = options[0]
    return {
        "comparison_id": new_id("dist_compare"),
        "entity_type": "fiduciary",
        "tax_year": tax_year,
        "recommended_distribution_amount": _money_str(recommended["distribution_amount"]),
        "options": _serialize(options),
        "provenance": {
            "computed_at": now_iso(),
            "durability_mode": durability_mode(),
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
        },
    }


def register_planning_tools(mcp) -> None:
    tool = make_enveloped_tool(mcp)

    @tool
    def plan_individual_safe_harbor(facts: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
        """Plan minimum-safe-harbor actions for an exact 2025/2026 individual case."""
        try:
            return plan_individual_safe_harbor_internal(facts, as_of=as_of)
        except UnsupportedExactCase as exc:
            return error_response_for_exact_case(exc)

    @tool
    def plan_fiduciary_safe_harbor(facts: dict[str, Any], as_of: str | None = None) -> dict[str, Any]:
        """Plan minimum-safe-harbor actions for an exact 2025/2026 fiduciary case."""
        try:
            return plan_fiduciary_safe_harbor_internal(facts, as_of=as_of)
        except UnsupportedExactCase as exc:
            return error_response_for_exact_case(exc)

    @tool
    def compare_individual_payment_strategies(
        facts: dict[str, Any],
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Compare exact individual payment strategies within the supported 2025/2026 scope."""
        try:
            return compare_individual_payment_strategies_internal(facts, as_of=as_of)
        except UnsupportedExactCase as exc:
            return error_response_for_exact_case(exc)

    @tool
    def compare_trust_distribution_strategies(
        fiduciary_facts: dict[str, Any],
        beneficiary_facts: dict[str, Any],
        candidate_distribution_amounts: list[float | int | str],
    ) -> dict[str, Any]:
        """Compare trust distribution amounts by exact incremental family tax cost."""
        try:
            return compare_trust_distribution_strategies_internal(
                fiduciary_facts,
                beneficiary_facts,
                candidate_distribution_amounts,
            )
        except UnsupportedExactCase as exc:
            return error_response_for_exact_case(exc)
