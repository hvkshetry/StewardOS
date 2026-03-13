"""Exact return kernels and MCP tools for household-tax-mcp."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from stewardos_lib.response_ops import make_enveloped_tool

from errors import UnsupportedExactCase, error_response_for_exact_case
from federal_individual_taxcalc import compute_individual_federal_breakdown_taxcalc
from models import FiduciaryTaxFacts, IndividualTaxFacts, parse_fiduciary_facts, parse_individual_facts
from store import durability_mode, new_id, now_iso, persist_run
from tax_config import (
    AUTHORITY_BUNDLE_VERSIONS,
    FEDERAL_FIDUCIARY_BRACKETS,
    FEDERAL_FIDUCIARY_KERNELS,
    FEDERAL_NIIT_RATE,
    FEDERAL_FIDUCIARY_NIIT_THRESHOLD,
    FEDERAL_FIDUCIARY_PREFERENTIAL_THRESHOLDS,
    FEDERAL_INDIVIDUAL_KERNELS,
    FEDERAL_INDIVIDUAL_KERNEL_REASON,
    FIDUCIARY_EXEMPTION,
    MASSACHUSETTS_KERNELS,
    MA_GENERAL_RATE,
    MA_PERSONAL_EXEMPTION,
    MA_SHORT_TERM_CAPITAL_GAINS_RATE,
    MA_SURTAX_RATE,
    MA_SURTAX_THRESHOLD,
    ZERO,
)


def _money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _money_str(value: Decimal) -> str:
    return f"{_money(value):.2f}"


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _money_str(value)
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    return value


def _ordinary_tax(amount: Decimal, brackets: tuple[tuple[Decimal, Decimal | None, Decimal], ...]) -> Decimal:
    taxable = max(ZERO, amount)
    tax = ZERO
    for lower, upper, rate in brackets:
        if taxable <= lower:
            break
        upper_bound = taxable if upper is None else min(taxable, upper)
        tax += (upper_bound - lower) * rate
        if upper is None or taxable <= upper:
            break
    return _money(tax)


def _preferential_tax(
    ordinary_taxable_income: Decimal,
    preferential_income: Decimal,
    *,
    zero_rate_top: Decimal,
    fifteen_rate_top: Decimal,
) -> Decimal:
    remaining = max(ZERO, preferential_income)
    if remaining == ZERO:
        return ZERO

    zero_band_remaining = max(ZERO, zero_rate_top - ordinary_taxable_income)
    zero_portion = min(remaining, zero_band_remaining)
    remaining -= zero_portion

    fifteen_band_remaining = max(ZERO, fifteen_rate_top - max(ordinary_taxable_income, zero_rate_top))
    fifteen_portion = min(remaining, fifteen_band_remaining)
    remaining -= fifteen_portion

    tax = (fifteen_portion * Decimal("0.15")) + (remaining * Decimal("0.20"))
    return _money(tax)


def _total_withholding(
    facts: IndividualTaxFacts | FiduciaryTaxFacts,
    *,
    jurisdiction: str | None = None,
) -> Decimal:
    return _money(
        sum(
            event.amount
            for event in facts.withholding_events
            if jurisdiction is None or event.jurisdiction == jurisdiction
        )
    )


def _total_estimates(
    facts: IndividualTaxFacts | FiduciaryTaxFacts,
    *,
    jurisdiction: str | None = None,
) -> Decimal:
    return _money(
        sum(
            event.amount
            for event in facts.estimated_payments
            if jurisdiction is None or event.jurisdiction == jurisdiction
        )
    )


def _individual_federal_breakdown(facts: IndividualTaxFacts) -> dict[str, Decimal | str]:
    return compute_individual_federal_breakdown_taxcalc(facts)


def _individual_massachusetts_breakdown(facts: IndividualTaxFacts) -> dict[str, Decimal]:
    tax_year = facts.tax_year
    if facts.massachusetts is not None:
        taxable_general_income = facts.massachusetts.taxable_general_income
        taxable_short_term_capital_gains = facts.massachusetts.taxable_short_term_capital_gains
        surtax_base = facts.massachusetts.surtax_base or (taxable_general_income + taxable_short_term_capital_gains)
        personal_exemption = facts.massachusetts.personal_exemption or ZERO
    else:
        personal_exemption = MA_PERSONAL_EXEMPTION[tax_year][facts.filing_status]
        taxable_general_income = max(
            ZERO,
            facts.wages
            + facts.taxable_interest
            + facts.ordinary_dividends
            + facts.qualified_dividends
            + facts.long_term_capital_gains
            + facts.other_ordinary_income
            - personal_exemption,
        )
        taxable_short_term_capital_gains = max(ZERO, facts.short_term_capital_gains)
        surtax_base = taxable_general_income + taxable_short_term_capital_gains

    ma_surtax_threshold = MA_SURTAX_THRESHOLD[tax_year]
    regular_tax = _money(
        (taxable_general_income * MA_GENERAL_RATE)
        + (taxable_short_term_capital_gains * MA_SHORT_TERM_CAPITAL_GAINS_RATE)
    )
    surtax = _money(max(ZERO, surtax_base - ma_surtax_threshold) * MA_SURTAX_RATE)
    return {
        "personal_exemption": _money(personal_exemption),
        "taxable_general_income": _money(taxable_general_income),
        "taxable_short_term_capital_gains": _money(taxable_short_term_capital_gains),
        "surtax_base": _money(surtax_base),
        "regular_tax": regular_tax,
        "surtax": surtax,
        "total_tax": _money(regular_tax + surtax),
    }


def _fiduciary_dni_components(facts: FiduciaryTaxFacts) -> dict[str, Decimal]:
    ordinary_components = {
        "taxable_interest": facts.taxable_interest,
        "ordinary_dividends": facts.ordinary_dividends,
        "other_ordinary_income": facts.other_ordinary_income,
        "qualified_dividends": facts.qualified_dividends,
    }
    if facts.capital_gains_in_dni:
        ordinary_components["long_term_capital_gains"] = facts.long_term_capital_gains
    remaining_deductions = facts.deductions
    for key in ("taxable_interest", "ordinary_dividends", "other_ordinary_income", "qualified_dividends", "long_term_capital_gains"):
        if key not in ordinary_components:
            continue
        if remaining_deductions <= ZERO:
            break
        reduction = min(ordinary_components[key], remaining_deductions)
        ordinary_components[key] -= reduction
        remaining_deductions -= reduction
    return {key: _money(value) for key, value in ordinary_components.items() if value > ZERO}


def _fiduciary_federal_breakdown(facts: FiduciaryTaxFacts, *, distribution_amount: Decimal = ZERO) -> dict[str, Any]:
    tax_year = facts.tax_year
    exemption_amount = facts.exemption_amount
    if exemption_amount is None:
        key = "estate" if facts.fiduciary_kind == "estate" else "complex_trust"
        exemption_amount = FIDUCIARY_EXEMPTION[key]

    dni_components = _fiduciary_dni_components(facts)
    distributable_net_income = _money(sum(dni_components.values()))
    distribution_deduction = _money(min(max(ZERO, distribution_amount), distributable_net_income))

    distributed_character: dict[str, Decimal] = {}
    if distribution_deduction > ZERO and distributable_net_income > ZERO:
        for key, amount in dni_components.items():
            share = amount / distributable_net_income
            distributed_character[key] = _money(distribution_deduction * share)
    else:
        distributed_character = {key: ZERO for key in dni_components}

    gross_ordinary_income = (
        facts.taxable_interest
        + facts.ordinary_dividends
        + facts.short_term_capital_gains
        + facts.other_ordinary_income
    )
    gross_preferential_income = facts.qualified_dividends + facts.long_term_capital_gains
    gross_income = gross_ordinary_income + gross_preferential_income

    deductions_before_exemption = facts.deductions + distribution_deduction
    taxable_before_exemption = max(ZERO, gross_income - deductions_before_exemption)
    taxable_income = max(ZERO, taxable_before_exemption - exemption_amount)

    deduction_pool = facts.deductions + distribution_deduction + exemption_amount
    ordinary_taxable_income = max(ZERO, gross_ordinary_income - deduction_pool)
    preferential_taxable_income = max(ZERO, taxable_income - ordinary_taxable_income)

    fiduciary_brackets = FEDERAL_FIDUCIARY_BRACKETS[tax_year]
    fiduciary_pref_thresholds = FEDERAL_FIDUCIARY_PREFERENTIAL_THRESHOLDS[tax_year]
    fiduciary_niit_threshold = FEDERAL_FIDUCIARY_NIIT_THRESHOLD[tax_year]

    regular_tax = _ordinary_tax(ordinary_taxable_income, fiduciary_brackets)
    regular_tax += _preferential_tax(
        ordinary_taxable_income,
        preferential_taxable_income,
        zero_rate_top=fiduciary_pref_thresholds["zero_rate_top"],
        fifteen_rate_top=fiduciary_pref_thresholds["fifteen_rate_top"],
    )

    undistributed_nii = facts.taxable_interest + facts.ordinary_dividends + facts.qualified_dividends
    undistributed_nii += facts.short_term_capital_gains + facts.long_term_capital_gains
    distributed_nii = sum(distributed_character.values()) if distributed_character else ZERO
    undistributed_nii = max(ZERO, undistributed_nii - distributed_nii)
    adjusted_gross_income = max(ZERO, gross_income - facts.deductions - distribution_deduction)
    niit_base = min(undistributed_nii, max(ZERO, adjusted_gross_income - fiduciary_niit_threshold))
    niit = _money(niit_base * FEDERAL_NIIT_RATE)

    return {
        "adjusted_gross_income": _money(adjusted_gross_income),
        "distributable_net_income": distributable_net_income,
        "distribution_deduction": distribution_deduction,
        "distributed_character": {key: _money(value) for key, value in distributed_character.items()},
        "deductions": _money(facts.deductions),
        "exemption_amount": _money(exemption_amount),
        "taxable_income": _money(taxable_income),
        "ordinary_taxable_income": _money(ordinary_taxable_income),
        "preferential_taxable_income": _money(preferential_taxable_income),
        "tax_before_credits": _money(regular_tax),
        "alternative_minimum_tax": ZERO,
        "net_investment_income_tax": _money(niit),
        "total_tax": _money(regular_tax + niit),
    }


def _fiduciary_massachusetts_breakdown(
    facts: FiduciaryTaxFacts,
    *,
    distribution_deduction: Decimal = ZERO,
    distributed_character: dict[str, Decimal] | None = None,
) -> dict[str, Decimal]:
    tax_year = facts.tax_year
    ma_surtax_threshold = MA_SURTAX_THRESHOLD[tax_year]

    if facts.massachusetts is not None:
        taxable_general_income = facts.massachusetts.taxable_general_income
        taxable_short_term_capital_gains = facts.massachusetts.taxable_short_term_capital_gains
        surtax_base = facts.massachusetts.surtax_base or (taxable_general_income + taxable_short_term_capital_gains)
    else:
        distributed_character = distributed_character or {}
        taxable_general_income = max(
            ZERO,
            facts.taxable_interest
            + facts.ordinary_dividends
            + facts.qualified_dividends
            + facts.long_term_capital_gains
            + facts.other_ordinary_income
            - facts.deductions
            - distribution_deduction
            - (facts.exemption_amount or (FIDUCIARY_EXEMPTION["estate"] if facts.fiduciary_kind == "estate" else FIDUCIARY_EXEMPTION["complex_trust"])),
        )
        taxable_short_term_capital_gains = max(ZERO, facts.short_term_capital_gains)
        if distributed_character:
            taxable_general_income = max(
                ZERO,
                taxable_general_income
                - distributed_character.get("taxable_interest", ZERO)
                - distributed_character.get("ordinary_dividends", ZERO)
                - distributed_character.get("other_ordinary_income", ZERO)
                - distributed_character.get("qualified_dividends", ZERO)
                - distributed_character.get("long_term_capital_gains", ZERO),
            )
        surtax_base = taxable_general_income + taxable_short_term_capital_gains

    regular_tax = _money(
        (taxable_general_income * MA_GENERAL_RATE)
        + (taxable_short_term_capital_gains * MA_SHORT_TERM_CAPITAL_GAINS_RATE)
    )
    surtax = _money(max(ZERO, surtax_base - ma_surtax_threshold) * MA_SURTAX_RATE)
    return {
        "taxable_general_income": _money(taxable_general_income),
        "taxable_short_term_capital_gains": _money(taxable_short_term_capital_gains),
        "surtax_base": _money(surtax_base),
        "regular_tax": regular_tax,
        "surtax": surtax,
        "total_tax": _money(regular_tax + surtax),
    }


def _individual_return_breakdown(facts: IndividualTaxFacts) -> dict[str, Any]:
    federal = _individual_federal_breakdown(facts)
    massachusetts = _individual_massachusetts_breakdown(facts)
    combined_total_tax = _money(federal["total_tax"] + massachusetts["total_tax"])
    withholding_total = _total_withholding(facts)
    estimated_total = _total_estimates(facts)
    return {
        "entity_type": "individual",
        "tax_year": facts.tax_year,
        "federal": federal,
        "massachusetts": massachusetts,
        "combined_total_tax": combined_total_tax,
        "withholding_total": withholding_total,
        "estimated_payments_total": estimated_total,
        "projected_balance_due": _money(max(ZERO, combined_total_tax - withholding_total - estimated_total)),
    }


def _fiduciary_return_breakdown(facts: FiduciaryTaxFacts, *, distribution_amount: Decimal = ZERO) -> dict[str, Any]:
    federal = _fiduciary_federal_breakdown(facts, distribution_amount=distribution_amount)
    massachusetts = _fiduciary_massachusetts_breakdown(
        facts,
        distribution_deduction=federal["distribution_deduction"],
        distributed_character=federal["distributed_character"],
    )
    combined_total_tax = _money(federal["total_tax"] + massachusetts["total_tax"])
    withholding_total = _total_withholding(facts)
    estimated_total = _total_estimates(facts)
    return {
        "entity_type": "fiduciary",
        "tax_year": facts.tax_year,
        "federal": federal,
        "massachusetts": massachusetts,
        "combined_total_tax": combined_total_tax,
        "withholding_total": withholding_total,
        "estimated_payments_total": estimated_total,
        "projected_balance_due": _money(max(ZERO, combined_total_tax - withholding_total - estimated_total)),
    }


def compute_individual_return_exact_internal(facts: dict[str, Any]) -> dict[str, Any]:
    from readiness import assess_exact_support_internal

    assessment = assess_exact_support_internal("individual", facts)
    if not assessment["supported"]:
        raise UnsupportedExactCase(assessment["unsupported_reasons"])

    normalized_facts = parse_individual_facts(facts)
    tax_year = normalized_facts.tax_year
    breakdown = _individual_return_breakdown(normalized_facts)
    run_id = new_id("tax_run")
    result = {
        "run_id": run_id,
        "entity_type": "individual",
        "tax_year": tax_year,
        "facts": normalized_facts.to_dict(),
        "return": _serialize(breakdown),
        "provenance": {
            "computed_at": now_iso(),
            "durability_mode": durability_mode(),
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
            "federal_kernel": FEDERAL_INDIVIDUAL_KERNELS[tax_year],
            "federal_kernel_reason": FEDERAL_INDIVIDUAL_KERNEL_REASON,
            "massachusetts_kernel": MASSACHUSETTS_KERNELS[tax_year],
        },
    }
    persist_run(
        {
            "run_id": run_id,
            "tool_name": "compute_individual_return_exact",
            "entity_type": "individual",
            "tax_year": tax_year,
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
            "facts": normalized_facts.to_dict(),
            "result": result,
        }
    )
    return result


def compute_fiduciary_return_exact_internal(facts: dict[str, Any]) -> dict[str, Any]:
    from readiness import assess_exact_support_internal

    assessment = assess_exact_support_internal("fiduciary", facts)
    if not assessment["supported"]:
        raise UnsupportedExactCase(assessment["unsupported_reasons"])

    normalized_facts = parse_fiduciary_facts(facts)
    tax_year = normalized_facts.tax_year
    breakdown = _fiduciary_return_breakdown(normalized_facts)
    run_id = new_id("tax_run")
    result = {
        "run_id": run_id,
        "entity_type": "fiduciary",
        "tax_year": tax_year,
        "facts": normalized_facts.to_dict(),
        "return": _serialize(breakdown),
        "provenance": {
            "computed_at": now_iso(),
            "durability_mode": durability_mode(),
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
            "federal_kernel": FEDERAL_FIDUCIARY_KERNELS[tax_year],
            "massachusetts_kernel": MASSACHUSETTS_KERNELS[tax_year],
        },
    }
    persist_run(
        {
            "run_id": run_id,
            "tool_name": "compute_fiduciary_return_exact",
            "entity_type": "fiduciary",
            "tax_year": tax_year,
            "authority_bundle_version": AUTHORITY_BUNDLE_VERSIONS[tax_year],
            "facts": normalized_facts.to_dict(),
            "result": result,
        }
    )
    return result


def register_return_tools(mcp) -> None:
    tool = make_enveloped_tool(mcp)

    @tool
    def compute_individual_return_exact(facts: dict[str, Any]) -> dict[str, Any]:
        """Compute a 2025/2026 exact individual return for the supported US+MA scope."""
        try:
            return compute_individual_return_exact_internal(facts)
        except UnsupportedExactCase as exc:
            return error_response_for_exact_case(exc)

    @tool
    def compute_fiduciary_return_exact(facts: dict[str, Any]) -> dict[str, Any]:
        """Compute a 2025/2026 exact fiduciary return for the supported US+MA scope."""
        try:
            return compute_fiduciary_return_exact_internal(facts)
        except UnsupportedExactCase as exc:
            return error_response_for_exact_case(exc)
