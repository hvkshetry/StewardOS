"""Canonical facts models for the household-tax exact engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from tax_config import (
    ANNUALIZED_INCOME_PERIOD_END_DATES,
    DEFAULT_TAX_YEAR,
    FIDUCIARY_RECOGNIZED_UNSUPPORTED_FIELDS,
    INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS,
    SUPPORTED_ENTITY_TYPES,
    SUPPORTED_FIDUCIARY_KINDS,
    SUPPORTED_FILING_STATUSES,
    SUPPORTED_JURISDICTIONS,
    SUPPORTED_STATE,
    SUPPORTED_TAX_YEARS,
    ZERO,
)


def as_decimal(value: Any, *, field_name: str) -> Decimal:
    if value in (None, ""):
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:  # pragma: no cover - exercised via caller
        raise ValueError(f"{field_name} must be numeric") from exc


def as_bool(value: Any, *, field_name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
    raise ValueError(f"{field_name} must be boolean")


def as_int(value: Any, *, field_name: str, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def as_date(value: Any, *, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc
    raise ValueError(f"{field_name} must be YYYY-MM-DD")


def _ensure_mapping(payload: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return payload


def _reject_unknown_fields(payload: Mapping[str, Any], *, allowed: Iterable[str], label: str) -> None:
    unknown = sorted(set(payload) - set(allowed))
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _serialize_decimal(value: Decimal) -> str:
    return f"{value:.2f}"


@dataclass(frozen=True)
class DatedAmount:
    payment_date: date
    amount: Decimal
    jurisdiction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_date": self.payment_date.isoformat(),
            "amount": _serialize_decimal(self.amount),
            "jurisdiction": self.jurisdiction,
        }


@dataclass(frozen=True)
class WithholdingEvent(DatedAmount):
    treat_as_ratable: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["treat_as_ratable"] = self.treat_as_ratable
        return payload


@dataclass(frozen=True)
class PriorYearFacts:
    total_tax: Decimal
    adjusted_gross_income: Decimal
    massachusetts_total_tax: Decimal | None = None
    full_year_return: bool = True
    filed: bool = True
    first_year_massachusetts_fiduciary: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "total_tax": _serialize_decimal(self.total_tax),
            "adjusted_gross_income": _serialize_decimal(self.adjusted_gross_income),
            "full_year_return": self.full_year_return,
            "filed": self.filed,
            "first_year_massachusetts_fiduciary": self.first_year_massachusetts_fiduciary,
        }
        if self.massachusetts_total_tax is not None:
            payload["massachusetts_total_tax"] = _serialize_decimal(self.massachusetts_total_tax)
        return payload


@dataclass(frozen=True)
class MassachusettsIndividualBase:
    taxable_general_income: Decimal
    taxable_short_term_capital_gains: Decimal = ZERO
    surtax_base: Decimal | None = None
    personal_exemption: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "taxable_general_income": _serialize_decimal(self.taxable_general_income),
            "taxable_short_term_capital_gains": _serialize_decimal(self.taxable_short_term_capital_gains),
        }
        if self.surtax_base is not None:
            payload["surtax_base"] = _serialize_decimal(self.surtax_base)
        if self.personal_exemption is not None:
            payload["personal_exemption"] = _serialize_decimal(self.personal_exemption)
        return payload


@dataclass(frozen=True)
class MassachusettsFiduciaryBase:
    taxable_general_income: Decimal
    taxable_short_term_capital_gains: Decimal = ZERO
    surtax_base: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "taxable_general_income": _serialize_decimal(self.taxable_general_income),
            "taxable_short_term_capital_gains": _serialize_decimal(self.taxable_short_term_capital_gains),
        }
        if self.surtax_base is not None:
            payload["surtax_base"] = _serialize_decimal(self.surtax_base)
        return payload


@dataclass(frozen=True)
class ItemizedDeductions:
    """Schedule A category breakdown for itemized deductions."""
    medical_expenses: Decimal = ZERO
    state_local_income_taxes: Decimal = ZERO
    real_estate_taxes: Decimal = ZERO
    mortgage_interest: Decimal = ZERO
    charitable_cash: Decimal = ZERO
    charitable_noncash: Decimal = ZERO
    casualty_loss: Decimal = ZERO
    other: Decimal = ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "medical_expenses": _serialize_decimal(self.medical_expenses),
            "state_local_income_taxes": _serialize_decimal(self.state_local_income_taxes),
            "real_estate_taxes": _serialize_decimal(self.real_estate_taxes),
            "mortgage_interest": _serialize_decimal(self.mortgage_interest),
            "charitable_cash": _serialize_decimal(self.charitable_cash),
            "charitable_noncash": _serialize_decimal(self.charitable_noncash),
            "casualty_loss": _serialize_decimal(self.casualty_loss),
            "other": _serialize_decimal(self.other),
        }


_ITEMIZED_FIELDS = {
    "medical_expenses",
    "state_local_income_taxes",
    "real_estate_taxes",
    "mortgage_interest",
    "charitable_cash",
    "charitable_noncash",
    "casualty_loss",
    "other",
}


@dataclass(frozen=True)
class AnnualizedIndividualPeriod:
    period_end: date
    wages: Decimal = ZERO
    taxable_interest: Decimal = ZERO
    ordinary_dividends: Decimal = ZERO
    qualified_dividends: Decimal = ZERO
    short_term_capital_gains: Decimal = ZERO
    long_term_capital_gains: Decimal = ZERO
    other_ordinary_income: Decimal = ZERO
    above_line_deductions: Decimal = ZERO
    massachusetts: MassachusettsIndividualBase | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "period_end": self.period_end.isoformat(),
            "wages": _serialize_decimal(self.wages),
            "taxable_interest": _serialize_decimal(self.taxable_interest),
            "ordinary_dividends": _serialize_decimal(self.ordinary_dividends),
            "qualified_dividends": _serialize_decimal(self.qualified_dividends),
            "short_term_capital_gains": _serialize_decimal(self.short_term_capital_gains),
            "long_term_capital_gains": _serialize_decimal(self.long_term_capital_gains),
            "other_ordinary_income": _serialize_decimal(self.other_ordinary_income),
            "above_line_deductions": _serialize_decimal(self.above_line_deductions),
        }
        if self.massachusetts is not None:
            payload["massachusetts"] = self.massachusetts.to_dict()
        return payload


@dataclass(frozen=True)
class AnnualizedFiduciaryPeriod:
    period_end: date
    taxable_interest: Decimal = ZERO
    ordinary_dividends: Decimal = ZERO
    qualified_dividends: Decimal = ZERO
    short_term_capital_gains: Decimal = ZERO
    long_term_capital_gains: Decimal = ZERO
    other_ordinary_income: Decimal = ZERO
    deductions: Decimal = ZERO
    massachusetts: MassachusettsFiduciaryBase | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "period_end": self.period_end.isoformat(),
            "taxable_interest": _serialize_decimal(self.taxable_interest),
            "ordinary_dividends": _serialize_decimal(self.ordinary_dividends),
            "qualified_dividends": _serialize_decimal(self.qualified_dividends),
            "short_term_capital_gains": _serialize_decimal(self.short_term_capital_gains),
            "long_term_capital_gains": _serialize_decimal(self.long_term_capital_gains),
            "other_ordinary_income": _serialize_decimal(self.other_ordinary_income),
            "deductions": _serialize_decimal(self.deductions),
        }
        if self.massachusetts is not None:
            payload["massachusetts"] = self.massachusetts.to_dict()
        return payload


@dataclass(frozen=True)
class IndividualTaxFacts:
    tax_year: int
    residence_state: str
    filing_status: str
    wages: Decimal = ZERO
    taxable_interest: Decimal = ZERO
    ordinary_dividends: Decimal = ZERO
    qualified_dividends: Decimal = ZERO
    short_term_capital_gains: Decimal = ZERO
    long_term_capital_gains: Decimal = ZERO
    other_ordinary_income: Decimal = ZERO
    above_line_deductions: Decimal = ZERO
    itemized_deductions: ItemizedDeductions | None = None
    dependents_under_17: int = 0
    dependents_under_18: int = 0
    withholding_events: tuple[WithholdingEvent, ...] = field(default_factory=tuple)
    estimated_payments: tuple[DatedAmount, ...] = field(default_factory=tuple)
    annualized_periods: tuple[AnnualizedIndividualPeriod, ...] = field(default_factory=tuple)
    prior_year: PriorYearFacts | None = None
    massachusetts: MassachusettsIndividualBase | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tax_year": self.tax_year,
            "residence_state": self.residence_state,
            "filing_status": self.filing_status,
            "wages": _serialize_decimal(self.wages),
            "taxable_interest": _serialize_decimal(self.taxable_interest),
            "ordinary_dividends": _serialize_decimal(self.ordinary_dividends),
            "qualified_dividends": _serialize_decimal(self.qualified_dividends),
            "short_term_capital_gains": _serialize_decimal(self.short_term_capital_gains),
            "long_term_capital_gains": _serialize_decimal(self.long_term_capital_gains),
            "other_ordinary_income": _serialize_decimal(self.other_ordinary_income),
            "above_line_deductions": _serialize_decimal(self.above_line_deductions),
            "dependents_under_17": self.dependents_under_17,
            "dependents_under_18": self.dependents_under_18,
            "withholding_events": [event.to_dict() for event in self.withholding_events],
            "estimated_payments": [payment.to_dict() for payment in self.estimated_payments],
        }
        if self.annualized_periods:
            payload["annualized_periods"] = [period.to_dict() for period in self.annualized_periods]
        if self.itemized_deductions is not None:
            payload["itemized_deductions"] = self.itemized_deductions.to_dict()
        if self.prior_year is not None:
            payload["prior_year"] = self.prior_year.to_dict()
        if self.massachusetts is not None:
            payload["massachusetts"] = self.massachusetts.to_dict()
        return payload


@dataclass(frozen=True)
class FiduciaryTaxFacts:
    tax_year: int
    residence_state: str
    fiduciary_kind: str
    taxable_interest: Decimal = ZERO
    ordinary_dividends: Decimal = ZERO
    qualified_dividends: Decimal = ZERO
    short_term_capital_gains: Decimal = ZERO
    long_term_capital_gains: Decimal = ZERO
    other_ordinary_income: Decimal = ZERO
    deductions: Decimal = ZERO
    exemption_amount: Decimal | None = None
    capital_gains_in_dni: bool = False
    withholding_events: tuple[WithholdingEvent, ...] = field(default_factory=tuple)
    estimated_payments: tuple[DatedAmount, ...] = field(default_factory=tuple)
    annualized_periods: tuple[AnnualizedFiduciaryPeriod, ...] = field(default_factory=tuple)
    prior_year: PriorYearFacts | None = None
    massachusetts: MassachusettsFiduciaryBase | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tax_year": self.tax_year,
            "residence_state": self.residence_state,
            "fiduciary_kind": self.fiduciary_kind,
            "taxable_interest": _serialize_decimal(self.taxable_interest),
            "ordinary_dividends": _serialize_decimal(self.ordinary_dividends),
            "qualified_dividends": _serialize_decimal(self.qualified_dividends),
            "short_term_capital_gains": _serialize_decimal(self.short_term_capital_gains),
            "long_term_capital_gains": _serialize_decimal(self.long_term_capital_gains),
            "other_ordinary_income": _serialize_decimal(self.other_ordinary_income),
            "deductions": _serialize_decimal(self.deductions),
            "capital_gains_in_dni": self.capital_gains_in_dni,
            "withholding_events": [event.to_dict() for event in self.withholding_events],
            "estimated_payments": [payment.to_dict() for payment in self.estimated_payments],
        }
        if self.annualized_periods:
            payload["annualized_periods"] = [period.to_dict() for period in self.annualized_periods]
        if self.exemption_amount is not None:
            payload["exemption_amount"] = _serialize_decimal(self.exemption_amount)
        if self.prior_year is not None:
            payload["prior_year"] = self.prior_year.to_dict()
        if self.massachusetts is not None:
            payload["massachusetts"] = self.massachusetts.to_dict()
        return payload


_COMMON_PAYMENT_FIELDS = {"payment_date", "amount", "jurisdiction"}
_WITHHOLDING_FIELDS = _COMMON_PAYMENT_FIELDS | {"treat_as_ratable"}
_PRIOR_YEAR_FIELDS = {
    "total_tax",
    "adjusted_gross_income",
    "massachusetts_total_tax",
    "full_year_return",
    "filed",
    "first_year_massachusetts_fiduciary",
}
_MASS_INDIVIDUAL_FIELDS = {
    "taxable_general_income",
    "taxable_short_term_capital_gains",
    "surtax_base",
    "personal_exemption",
}
_MASS_FIDUCIARY_FIELDS = {
    "taxable_general_income",
    "taxable_short_term_capital_gains",
    "surtax_base",
}
_ANNUALIZED_INDIVIDUAL_PERIOD_FIELDS = {
    "period_end",
    "wages",
    "taxable_interest",
    "ordinary_dividends",
    "qualified_dividends",
    "short_term_capital_gains",
    "long_term_capital_gains",
    "other_ordinary_income",
    "above_line_deductions",
    "massachusetts",
}
_ANNUALIZED_FIDUCIARY_PERIOD_FIELDS = {
    "period_end",
    "taxable_interest",
    "ordinary_dividends",
    "qualified_dividends",
    "short_term_capital_gains",
    "long_term_capital_gains",
    "other_ordinary_income",
    "deductions",
    "massachusetts",
}

_INDIVIDUAL_FIELDS = {
    "tax_year",
    "jurisdictions",
    "residence_state",
    "filing_status",
    "wages",
    "taxable_interest",
    "ordinary_dividends",
    "qualified_dividends",
    "short_term_capital_gains",
    "long_term_capital_gains",
    "other_ordinary_income",
    "above_line_deductions",
    "itemized_deductions",
    "dependents_under_17",
    "dependents_under_18",
    "withholding_events",
    "estimated_payments",
    "annualized_periods",
    "prior_year",
    "massachusetts",
} | INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS

_FIDUCIARY_FIELDS = {
    "tax_year",
    "jurisdictions",
    "residence_state",
    "fiduciary_kind",
    "taxable_interest",
    "ordinary_dividends",
    "qualified_dividends",
    "short_term_capital_gains",
    "long_term_capital_gains",
    "other_ordinary_income",
    "deductions",
    "exemption_amount",
    "capital_gains_in_dni",
    "withholding_events",
    "estimated_payments",
    "annualized_periods",
    "prior_year",
    "massachusetts",
} | FIDUCIARY_RECOGNIZED_UNSUPPORTED_FIELDS


def parse_entity_type(entity_type: str) -> str:
    normalized = str(entity_type or "").strip().lower()
    if normalized not in SUPPORTED_ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of: {', '.join(SUPPORTED_ENTITY_TYPES)}")
    return normalized


def parse_jurisdictions(payload: Mapping[str, Any]) -> tuple[str, ...]:
    raw = payload.get("jurisdictions") or SUPPORTED_JURISDICTIONS
    if not isinstance(raw, (list, tuple)):
        raise ValueError("jurisdictions must be a list")
    normalized = tuple(str(item).strip().upper() for item in raw)
    if normalized != SUPPORTED_JURISDICTIONS:
        raise ValueError(
            f"jurisdictions must be {list(SUPPORTED_JURISDICTIONS)} for the exact "
            f"{'+'.join(SUPPORTED_JURISDICTIONS)} scope"
        )
    return normalized


def parse_prior_year(payload: Any) -> PriorYearFacts | None:
    if payload in (None, {}):
        return None
    data = _ensure_mapping(payload, label="prior_year")
    _reject_unknown_fields(data, allowed=_PRIOR_YEAR_FIELDS, label="prior_year")
    return PriorYearFacts(
        total_tax=as_decimal(data.get("total_tax"), field_name="prior_year.total_tax"),
        adjusted_gross_income=as_decimal(
            data.get("adjusted_gross_income"),
            field_name="prior_year.adjusted_gross_income",
        ),
        massachusetts_total_tax=(
            as_decimal(data.get("massachusetts_total_tax"), field_name="prior_year.massachusetts_total_tax")
            if data.get("massachusetts_total_tax") not in (None, "")
            else None
        ),
        full_year_return=as_bool(data.get("full_year_return"), field_name="prior_year.full_year_return", default=True),
        filed=as_bool(data.get("filed"), field_name="prior_year.filed", default=True),
        first_year_massachusetts_fiduciary=as_bool(
            data.get("first_year_massachusetts_fiduciary"),
            field_name="prior_year.first_year_massachusetts_fiduciary",
            default=False,
        ),
    )


def parse_dated_amounts(payload: Any, *, field_name: str) -> tuple[DatedAmount, ...]:
    if payload in (None, []):
        return ()
    if not isinstance(payload, list):
        raise ValueError(f"{field_name} must be a list")
    out: list[DatedAmount] = []
    for idx, item in enumerate(payload):
        data = _ensure_mapping(item, label=f"{field_name}[{idx}]")
        _reject_unknown_fields(data, allowed=_COMMON_PAYMENT_FIELDS, label=f"{field_name}[{idx}]")
        amount = as_decimal(data.get("amount"), field_name=f"{field_name}[{idx}].amount")
        if amount < ZERO:
            raise ValueError(f"{field_name}[{idx}].amount must be non-negative")
        out.append(
            DatedAmount(
                payment_date=as_date(data.get("payment_date"), field_name=f"{field_name}[{idx}].payment_date"),
                amount=amount,
                jurisdiction=_parse_payment_jurisdiction(
                    data.get("jurisdiction"),
                    field_name=f"{field_name}[{idx}].jurisdiction",
                ),
            )
        )
    return tuple(out)


def parse_withholding_events(payload: Any) -> tuple[WithholdingEvent, ...]:
    if payload in (None, []):
        return ()
    if not isinstance(payload, list):
        raise ValueError("withholding_events must be a list")
    out: list[WithholdingEvent] = []
    for idx, item in enumerate(payload):
        data = _ensure_mapping(item, label=f"withholding_events[{idx}]")
        _reject_unknown_fields(data, allowed=_WITHHOLDING_FIELDS, label=f"withholding_events[{idx}]")
        amount = as_decimal(data.get("amount"), field_name=f"withholding_events[{idx}].amount")
        if amount < ZERO:
            raise ValueError(f"withholding_events[{idx}].amount must be non-negative")
        out.append(
            WithholdingEvent(
                payment_date=as_date(data.get("payment_date"), field_name=f"withholding_events[{idx}].payment_date"),
                amount=amount,
                jurisdiction=_parse_payment_jurisdiction(
                    data.get("jurisdiction"),
                    field_name=f"withholding_events[{idx}].jurisdiction",
                ),
                treat_as_ratable=as_bool(
                    data.get("treat_as_ratable"),
                    field_name=f"withholding_events[{idx}].treat_as_ratable",
                    default=True,
                ),
            )
        )
    return tuple(out)


def parse_massachusetts_individual(payload: Any) -> MassachusettsIndividualBase | None:
    if payload in (None, {}):
        return None
    data = _ensure_mapping(payload, label="massachusetts")
    _reject_unknown_fields(data, allowed=_MASS_INDIVIDUAL_FIELDS, label="massachusetts")
    return MassachusettsIndividualBase(
        taxable_general_income=as_decimal(
            data.get("taxable_general_income"),
            field_name="massachusetts.taxable_general_income",
        ),
        taxable_short_term_capital_gains=as_decimal(
            data.get("taxable_short_term_capital_gains"),
            field_name="massachusetts.taxable_short_term_capital_gains",
        ),
        surtax_base=(
            as_decimal(data.get("surtax_base"), field_name="massachusetts.surtax_base")
            if data.get("surtax_base") not in (None, "")
            else None
        ),
        personal_exemption=(
            as_decimal(data.get("personal_exemption"), field_name="massachusetts.personal_exemption")
            if data.get("personal_exemption") not in (None, "")
            else None
        ),
    )


def parse_massachusetts_fiduciary(payload: Any) -> MassachusettsFiduciaryBase | None:
    if payload in (None, {}):
        return None
    data = _ensure_mapping(payload, label="massachusetts")
    _reject_unknown_fields(data, allowed=_MASS_FIDUCIARY_FIELDS, label="massachusetts")
    return MassachusettsFiduciaryBase(
        taxable_general_income=as_decimal(
            data.get("taxable_general_income"),
            field_name="massachusetts.taxable_general_income",
        ),
        taxable_short_term_capital_gains=as_decimal(
            data.get("taxable_short_term_capital_gains"),
            field_name="massachusetts.taxable_short_term_capital_gains",
        ),
        surtax_base=(
            as_decimal(data.get("surtax_base"), field_name="massachusetts.surtax_base")
            if data.get("surtax_base") not in (None, "")
            else None
        ),
    )


def parse_itemized_deductions(payload: Any) -> ItemizedDeductions | None:
    if payload in (None, {}):
        return None
    data = _ensure_mapping(payload, label="itemized_deductions")
    _reject_unknown_fields(data, allowed=_ITEMIZED_FIELDS, label="itemized_deductions")
    return ItemizedDeductions(
        medical_expenses=as_decimal(data.get("medical_expenses"), field_name="itemized_deductions.medical_expenses"),
        state_local_income_taxes=as_decimal(
            data.get("state_local_income_taxes"), field_name="itemized_deductions.state_local_income_taxes"
        ),
        real_estate_taxes=as_decimal(data.get("real_estate_taxes"), field_name="itemized_deductions.real_estate_taxes"),
        mortgage_interest=as_decimal(data.get("mortgage_interest"), field_name="itemized_deductions.mortgage_interest"),
        charitable_cash=as_decimal(data.get("charitable_cash"), field_name="itemized_deductions.charitable_cash"),
        charitable_noncash=as_decimal(
            data.get("charitable_noncash"), field_name="itemized_deductions.charitable_noncash"
        ),
        casualty_loss=as_decimal(data.get("casualty_loss"), field_name="itemized_deductions.casualty_loss"),
        other=as_decimal(data.get("other"), field_name="itemized_deductions.other"),
    )


def _expected_annualized_period_end_dates(tax_year: int) -> tuple[date, ...]:
    return tuple(date.fromisoformat(value) for value in ANNUALIZED_INCOME_PERIOD_END_DATES[tax_year])


def parse_annualized_individual_periods(
    payload: Any,
    *,
    tax_year: int,
    require_massachusetts: bool,
) -> tuple[AnnualizedIndividualPeriod, ...]:
    if payload in (None, []):
        return ()
    if not isinstance(payload, list):
        raise ValueError("annualized_periods must be a list")
    period_end_dates = ANNUALIZED_INCOME_PERIOD_END_DATES[tax_year]
    if len(payload) != len(period_end_dates):
        raise ValueError(
            f"annualized_periods must contain {len(period_end_dates)} cumulative periods"
        )

    expected_dates = _expected_annualized_period_end_dates(tax_year)
    out: list[AnnualizedIndividualPeriod] = []
    saw_massachusetts = False
    for idx, item in enumerate(payload):
        data = _ensure_mapping(item, label=f"annualized_periods[{idx}]")
        _reject_unknown_fields(
            data,
            allowed=_ANNUALIZED_INDIVIDUAL_PERIOD_FIELDS,
            label=f"annualized_periods[{idx}]",
        )
        period_end = as_date(data.get("period_end"), field_name=f"annualized_periods[{idx}].period_end")
        if period_end != expected_dates[idx]:
            raise ValueError(
                f"annualized_periods[{idx}].period_end must be {expected_dates[idx].isoformat()}"
            )
        massachusetts = parse_massachusetts_individual(data.get("massachusetts"))
        if massachusetts is not None:
            saw_massachusetts = True
        out.append(
            AnnualizedIndividualPeriod(
                period_end=period_end,
                wages=as_decimal(data.get("wages"), field_name=f"annualized_periods[{idx}].wages"),
                taxable_interest=as_decimal(
                    data.get("taxable_interest"),
                    field_name=f"annualized_periods[{idx}].taxable_interest",
                ),
                ordinary_dividends=as_decimal(
                    data.get("ordinary_dividends"),
                    field_name=f"annualized_periods[{idx}].ordinary_dividends",
                ),
                qualified_dividends=as_decimal(
                    data.get("qualified_dividends"),
                    field_name=f"annualized_periods[{idx}].qualified_dividends",
                ),
                short_term_capital_gains=as_decimal(
                    data.get("short_term_capital_gains"),
                    field_name=f"annualized_periods[{idx}].short_term_capital_gains",
                ),
                long_term_capital_gains=as_decimal(
                    data.get("long_term_capital_gains"),
                    field_name=f"annualized_periods[{idx}].long_term_capital_gains",
                ),
                other_ordinary_income=as_decimal(
                    data.get("other_ordinary_income"),
                    field_name=f"annualized_periods[{idx}].other_ordinary_income",
                ),
                above_line_deductions=as_decimal(
                    data.get("above_line_deductions"),
                    field_name=f"annualized_periods[{idx}].above_line_deductions",
                ),
                massachusetts=massachusetts,
            )
        )

    if require_massachusetts and not saw_massachusetts:
        raise ValueError(
            "annualized_periods must include Massachusetts overrides when facts.massachusetts is provided"
        )
    if saw_massachusetts and not require_massachusetts:
        raise ValueError(
            "facts.massachusetts must be provided when annualized_periods include Massachusetts overrides"
        )
    return tuple(out)


def parse_annualized_fiduciary_periods(
    payload: Any,
    *,
    tax_year: int,
    require_massachusetts: bool,
) -> tuple[AnnualizedFiduciaryPeriod, ...]:
    if payload in (None, []):
        return ()
    if not isinstance(payload, list):
        raise ValueError("annualized_periods must be a list")
    period_end_dates = ANNUALIZED_INCOME_PERIOD_END_DATES[tax_year]
    if len(payload) != len(period_end_dates):
        raise ValueError(
            f"annualized_periods must contain {len(period_end_dates)} cumulative periods"
        )

    expected_dates = _expected_annualized_period_end_dates(tax_year)
    out: list[AnnualizedFiduciaryPeriod] = []
    saw_massachusetts = False
    for idx, item in enumerate(payload):
        data = _ensure_mapping(item, label=f"annualized_periods[{idx}]")
        _reject_unknown_fields(
            data,
            allowed=_ANNUALIZED_FIDUCIARY_PERIOD_FIELDS,
            label=f"annualized_periods[{idx}]",
        )
        period_end = as_date(data.get("period_end"), field_name=f"annualized_periods[{idx}].period_end")
        if period_end != expected_dates[idx]:
            raise ValueError(
                f"annualized_periods[{idx}].period_end must be {expected_dates[idx].isoformat()}"
            )
        massachusetts = parse_massachusetts_fiduciary(data.get("massachusetts"))
        if massachusetts is not None:
            saw_massachusetts = True
        out.append(
            AnnualizedFiduciaryPeriod(
                period_end=period_end,
                taxable_interest=as_decimal(
                    data.get("taxable_interest"),
                    field_name=f"annualized_periods[{idx}].taxable_interest",
                ),
                ordinary_dividends=as_decimal(
                    data.get("ordinary_dividends"),
                    field_name=f"annualized_periods[{idx}].ordinary_dividends",
                ),
                qualified_dividends=as_decimal(
                    data.get("qualified_dividends"),
                    field_name=f"annualized_periods[{idx}].qualified_dividends",
                ),
                short_term_capital_gains=as_decimal(
                    data.get("short_term_capital_gains"),
                    field_name=f"annualized_periods[{idx}].short_term_capital_gains",
                ),
                long_term_capital_gains=as_decimal(
                    data.get("long_term_capital_gains"),
                    field_name=f"annualized_periods[{idx}].long_term_capital_gains",
                ),
                other_ordinary_income=as_decimal(
                    data.get("other_ordinary_income"),
                    field_name=f"annualized_periods[{idx}].other_ordinary_income",
                ),
                deductions=as_decimal(
                    data.get("deductions"),
                    field_name=f"annualized_periods[{idx}].deductions",
                ),
                massachusetts=massachusetts,
            )
        )

    if require_massachusetts and not saw_massachusetts:
        raise ValueError(
            "annualized_periods must include Massachusetts overrides when facts.massachusetts is provided"
        )
    if saw_massachusetts and not require_massachusetts:
        raise ValueError(
            "facts.massachusetts must be provided when annualized_periods include Massachusetts overrides"
        )
    return tuple(out)


def _validate_individual_annualized_alignment(
    facts: IndividualTaxFacts,
) -> None:
    if not facts.annualized_periods:
        return
    final_period = facts.annualized_periods[-1]
    comparisons = {
        "wages": (facts.wages, final_period.wages),
        "taxable_interest": (facts.taxable_interest, final_period.taxable_interest),
        "ordinary_dividends": (facts.ordinary_dividends, final_period.ordinary_dividends),
        "qualified_dividends": (facts.qualified_dividends, final_period.qualified_dividends),
        "short_term_capital_gains": (facts.short_term_capital_gains, final_period.short_term_capital_gains),
        "long_term_capital_gains": (facts.long_term_capital_gains, final_period.long_term_capital_gains),
        "other_ordinary_income": (facts.other_ordinary_income, final_period.other_ordinary_income),
        "above_line_deductions": (facts.above_line_deductions, final_period.above_line_deductions),
    }
    for field_name, (expected, actual) in comparisons.items():
        if expected != actual:
            raise ValueError(
                f"annualized_periods final cumulative {field_name} must match full-year facts.{field_name}"
            )
    if facts.massachusetts is not None:
        if final_period.massachusetts is None:
            raise ValueError(
                "annualized_periods final cumulative massachusetts must match full-year facts.massachusetts"
            )
        massachusetts_comparisons = {
            "taxable_general_income": (
                facts.massachusetts.taxable_general_income,
                final_period.massachusetts.taxable_general_income,
            ),
            "taxable_short_term_capital_gains": (
                facts.massachusetts.taxable_short_term_capital_gains,
                final_period.massachusetts.taxable_short_term_capital_gains,
            ),
            "surtax_base": (facts.massachusetts.surtax_base, final_period.massachusetts.surtax_base),
            "personal_exemption": (
                facts.massachusetts.personal_exemption,
                final_period.massachusetts.personal_exemption,
            ),
        }
        for field_name, (expected, actual) in massachusetts_comparisons.items():
            if expected != actual:
                raise ValueError(
                    "annualized_periods final cumulative massachusetts"
                    f".{field_name} must match full-year facts.massachusetts.{field_name}"
                )


def _validate_fiduciary_annualized_alignment(
    facts: FiduciaryTaxFacts,
) -> None:
    if not facts.annualized_periods:
        return
    final_period = facts.annualized_periods[-1]
    comparisons = {
        "taxable_interest": (facts.taxable_interest, final_period.taxable_interest),
        "ordinary_dividends": (facts.ordinary_dividends, final_period.ordinary_dividends),
        "qualified_dividends": (facts.qualified_dividends, final_period.qualified_dividends),
        "short_term_capital_gains": (facts.short_term_capital_gains, final_period.short_term_capital_gains),
        "long_term_capital_gains": (facts.long_term_capital_gains, final_period.long_term_capital_gains),
        "other_ordinary_income": (facts.other_ordinary_income, final_period.other_ordinary_income),
        "deductions": (facts.deductions, final_period.deductions),
    }
    for field_name, (expected, actual) in comparisons.items():
        if expected != actual:
            raise ValueError(
                f"annualized_periods final cumulative {field_name} must match full-year facts.{field_name}"
            )
    if facts.massachusetts is not None:
        if final_period.massachusetts is None:
            raise ValueError(
                "annualized_periods final cumulative massachusetts must match full-year facts.massachusetts"
            )
        massachusetts_comparisons = {
            "taxable_general_income": (
                facts.massachusetts.taxable_general_income,
                final_period.massachusetts.taxable_general_income,
            ),
            "taxable_short_term_capital_gains": (
                facts.massachusetts.taxable_short_term_capital_gains,
                final_period.massachusetts.taxable_short_term_capital_gains,
            ),
            "surtax_base": (facts.massachusetts.surtax_base, final_period.massachusetts.surtax_base),
        }
        for field_name, (expected, actual) in massachusetts_comparisons.items():
            if expected != actual:
                raise ValueError(
                    "annualized_periods final cumulative massachusetts"
                    f".{field_name} must match full-year facts.massachusetts.{field_name}"
                )


def parse_individual_facts(payload: Any) -> IndividualTaxFacts:
    data = _ensure_mapping(payload, label="facts")
    _reject_unknown_fields(data, allowed=_INDIVIDUAL_FIELDS, label="facts")
    parse_jurisdictions(data)
    tax_year = int(data.get("tax_year", DEFAULT_TAX_YEAR))
    if tax_year not in SUPPORTED_TAX_YEARS:
        raise ValueError(f"tax_year must be one of {SUPPORTED_TAX_YEARS} for the exact scope")
    residence_state = str(data.get("residence_state") or "").strip().upper()
    filing_status = str(data.get("filing_status") or "").strip().lower()
    if filing_status not in SUPPORTED_FILING_STATUSES:
        raise ValueError(f"filing_status must be one of: {', '.join(SUPPORTED_FILING_STATUSES)}")
    if residence_state != SUPPORTED_STATE:
        raise ValueError("residence_state must be 'MA' for the exact US+MA scope")
    massachusetts = parse_massachusetts_individual(data.get("massachusetts"))

    itemized_deductions = parse_itemized_deductions(data.get("itemized_deductions"))

    annualized_periods = parse_annualized_individual_periods(
        data.get("annualized_periods"),
        tax_year=tax_year,
        require_massachusetts=massachusetts is not None,
    )

    if annualized_periods and itemized_deductions is not None:
        raise ValueError(
            "annualized_periods and itemized_deductions cannot both be provided; "
            "itemized deduction amounts are year-end figures not supported in annualized installment computation"
        )

    dependents_under_17 = as_int(data.get("dependents_under_17"), field_name="facts.dependents_under_17")
    dependents_under_18 = as_int(data.get("dependents_under_18"), field_name="facts.dependents_under_18")
    if dependents_under_17 < 0:
        raise ValueError("facts.dependents_under_17 must be non-negative")
    if dependents_under_18 < 0:
        raise ValueError("facts.dependents_under_18 must be non-negative")
    if dependents_under_17 > dependents_under_18:
        raise ValueError("facts.dependents_under_17 must not exceed facts.dependents_under_18")

    facts = IndividualTaxFacts(
        tax_year=tax_year,
        residence_state=residence_state,
        filing_status=filing_status,
        wages=as_decimal(data.get("wages"), field_name="facts.wages"),
        taxable_interest=as_decimal(data.get("taxable_interest"), field_name="facts.taxable_interest"),
        ordinary_dividends=as_decimal(data.get("ordinary_dividends"), field_name="facts.ordinary_dividends"),
        qualified_dividends=as_decimal(data.get("qualified_dividends"), field_name="facts.qualified_dividends"),
        short_term_capital_gains=as_decimal(
            data.get("short_term_capital_gains"),
            field_name="facts.short_term_capital_gains",
        ),
        long_term_capital_gains=as_decimal(
            data.get("long_term_capital_gains"),
            field_name="facts.long_term_capital_gains",
        ),
        other_ordinary_income=as_decimal(
            data.get("other_ordinary_income"),
            field_name="facts.other_ordinary_income",
        ),
        above_line_deductions=as_decimal(
            data.get("above_line_deductions"),
            field_name="facts.above_line_deductions",
        ),
        itemized_deductions=itemized_deductions,
        dependents_under_17=dependents_under_17,
        dependents_under_18=dependents_under_18,
        withholding_events=parse_withholding_events(data.get("withholding_events")),
        estimated_payments=parse_dated_amounts(data.get("estimated_payments"), field_name="estimated_payments"),
        annualized_periods=annualized_periods,
        prior_year=parse_prior_year(data.get("prior_year")),
        massachusetts=massachusetts,
    )
    _validate_individual_annualized_alignment(facts)
    return facts


def parse_fiduciary_facts(payload: Any) -> FiduciaryTaxFacts:
    data = _ensure_mapping(payload, label="facts")
    _reject_unknown_fields(data, allowed=_FIDUCIARY_FIELDS, label="facts")
    parse_jurisdictions(data)
    tax_year = int(data.get("tax_year", DEFAULT_TAX_YEAR))
    if tax_year not in SUPPORTED_TAX_YEARS:
        raise ValueError(f"tax_year must be one of {SUPPORTED_TAX_YEARS} for the exact scope")
    residence_state = str(data.get("residence_state") or "").strip().upper()
    fiduciary_kind = str(data.get("fiduciary_kind") or "").strip().lower()
    if residence_state != SUPPORTED_STATE:
        raise ValueError("residence_state must be 'MA' for the exact US+MA scope")
    if fiduciary_kind not in SUPPORTED_FIDUCIARY_KINDS:
        raise ValueError(f"fiduciary_kind must be one of: {', '.join(SUPPORTED_FIDUCIARY_KINDS)}")
    massachusetts = parse_massachusetts_fiduciary(data.get("massachusetts"))
    annualized_periods = parse_annualized_fiduciary_periods(
        data.get("annualized_periods"),
        tax_year=tax_year,
        require_massachusetts=massachusetts is not None,
    )
    facts = FiduciaryTaxFacts(
        tax_year=tax_year,
        residence_state=residence_state,
        fiduciary_kind=fiduciary_kind,
        taxable_interest=as_decimal(data.get("taxable_interest"), field_name="facts.taxable_interest"),
        ordinary_dividends=as_decimal(data.get("ordinary_dividends"), field_name="facts.ordinary_dividends"),
        qualified_dividends=as_decimal(data.get("qualified_dividends"), field_name="facts.qualified_dividends"),
        short_term_capital_gains=as_decimal(
            data.get("short_term_capital_gains"),
            field_name="facts.short_term_capital_gains",
        ),
        long_term_capital_gains=as_decimal(
            data.get("long_term_capital_gains"),
            field_name="facts.long_term_capital_gains",
        ),
        other_ordinary_income=as_decimal(
            data.get("other_ordinary_income"),
            field_name="facts.other_ordinary_income",
        ),
        deductions=as_decimal(data.get("deductions"), field_name="facts.deductions"),
        exemption_amount=(
            as_decimal(data.get("exemption_amount"), field_name="facts.exemption_amount")
            if data.get("exemption_amount") not in (None, "")
            else None
        ),
        capital_gains_in_dni=as_bool(
            data.get("capital_gains_in_dni"),
            field_name="facts.capital_gains_in_dni",
            default=False,
        ),
        withholding_events=parse_withholding_events(data.get("withholding_events")),
        estimated_payments=parse_dated_amounts(data.get("estimated_payments"), field_name="estimated_payments"),
        annualized_periods=annualized_periods,
        prior_year=parse_prior_year(data.get("prior_year")),
        massachusetts=massachusetts,
    )
    _validate_fiduciary_annualized_alignment(facts)
    return facts


def unsupported_features(entity_type: str, payload: Mapping[str, Any]) -> list[str]:
    normalized = parse_entity_type(entity_type)
    if normalized == "individual":
        keys = INDIVIDUAL_RECOGNIZED_UNSUPPORTED_FIELDS
    else:
        keys = FIDUCIARY_RECOGNIZED_UNSUPPORTED_FIELDS

    reasons: list[str] = []
    for field_name in sorted(keys):
        value = payload.get(field_name)
        if value in (None, "", False, 0, 0.0, [], {}):
            continue
        reasons.append(f"{field_name} is outside the exact US+MA scope")
    return reasons


def _parse_payment_jurisdiction(value: Any, *, field_name: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in {"US", "MA"}:
        raise ValueError(f"{field_name} must be 'US' or 'MA'")
    return normalized
