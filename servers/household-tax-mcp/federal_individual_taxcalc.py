"""Federal individual return kernel backed by Tax-Calculator."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
from taxcalc import Calculator, Policy, Records

from models import IndividualTaxFacts
from tax_config import ZERO

_MARS_BY_STATUS = {
    "single": 1,
    "married_filing_jointly": 2,
    "married_filing_separately": 3,
    "head_of_household": 4,
}


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_individual_federal_breakdown_taxcalc(facts: IndividualTaxFacts) -> dict[str, Decimal | str]:
    tax_year = facts.tax_year
    total_dividends = facts.ordinary_dividends + facts.qualified_dividends
    n_filers = 2 if facts.filing_status == "married_filing_jointly" else 1

    record: dict[str, float | int] = {
        "RECID": 1,
        "MARS": _MARS_BY_STATUS[facts.filing_status],
        "XTOT": n_filers + facts.dependents_under_18,
        "age_head": 40,
        "age_spouse": 40 if facts.filing_status == "married_filing_jointly" else 0,
        "elderly_dependents": 0,
        "e00200": float(facts.wages),
        "e00200p": float(facts.wages),
        "e00200s": 0.0,
        "e00300": float(facts.taxable_interest),
        "e00600": float(total_dividends),
        "e00650": float(facts.qualified_dividends),
        "p22250": float(facts.short_term_capital_gains),
        "p23250": float(facts.long_term_capital_gains),
        "c02900": float(facts.above_line_deductions),
        "n24": facts.dependents_under_17,
        "nu18": facts.dependents_under_18,
        "EIC": min(facts.dependents_under_17, 3),
    }

    if facts.itemized_deductions is not None:
        itm = facts.itemized_deductions
        record["e17500"] = float(itm.medical_expenses)
        record["e18400"] = float(itm.state_local_income_taxes)
        record["e18500"] = float(itm.real_estate_taxes)
        record["e19200"] = float(itm.mortgage_interest)
        record["e19800"] = float(itm.charitable_cash)
        record["e20100"] = float(itm.charitable_noncash)
        record["g20500"] = float(itm.casualty_loss)
        record["e20400"] = float(itm.other)

    records = Records(
        data=pd.DataFrame([record]),
        start_year=tax_year,
        gfactors=None,
        weights=None,
        adjust_ratios=None,
        exact_calculations=True,
    )
    policy = Policy()
    policy.set_year(tax_year)
    calc = Calculator(policy=policy, records=records)
    calc.advance_to_year(tax_year)
    calc.calc_all()

    adjusted_gross_income = _decimal(calc.array("c00100")[0])
    standard_deduction = _decimal(calc.array("standard")[0])
    itemized_deduction = _decimal(calc.array("c04470")[0])

    if standard_deduction > ZERO:
        deduction_type = "standard"
        deduction = standard_deduction
    else:
        deduction_type = "itemized"
        deduction = itemized_deduction

    taxable_income = _decimal(calc.array("c04800")[0])
    preferential_income = _decimal(facts.qualified_dividends + facts.long_term_capital_gains)
    preferential_taxable_income = min(preferential_income, taxable_income)
    ordinary_taxable_income = max(ZERO, taxable_income - preferential_taxable_income)

    total_tax = _decimal(calc.array("iitax")[0])
    niit = _decimal(calc.array("niit")[0])
    amt = _decimal(calc.array("c09600")[0])

    # Regular tax on taxable income (before credits and AMT).
    regular_tax = _decimal(calc.array("c05800")[0])
    tax_before_credits = regular_tax + amt

    # Child and dependent credits (composite of CTC + ACTC + ODC + ctc_new).
    try:
        ctc_total = _decimal(calc.array("ctc_total")[0])
    except KeyError:
        # Older Tax-Calculator versions may not have ctc_total; fall back to components.
        c07220 = _decimal(calc.array("c07220")[0])
        c11070 = _decimal(calc.array("c11070")[0])
        try:
            odc = _decimal(calc.array("odc")[0])
        except KeyError:
            odc = ZERO
        try:
            ctc_new = _decimal(calc.array("ctc_new")[0])
        except KeyError:
            ctc_new = ZERO
        ctc_total = c07220 + c11070 + odc + ctc_new

    # Refundable portion of CTC (ACTC / c11070).
    try:
        ctc_refundable = _decimal(calc.array("ctc_refundable")[0])
    except KeyError:
        try:
            ctc_refundable = _decimal(calc.array("c11070")[0])
        except KeyError:
            ctc_refundable = ZERO

    # SALT actually used after cap (for MA coordination reference).
    try:
        salt_after_cap = _decimal(calc.array("c18300")[0])
    except KeyError:
        salt_after_cap = ZERO

    return {
        "adjusted_gross_income": adjusted_gross_income,
        "deduction": deduction,
        "deduction_type": deduction_type,
        "taxable_income": taxable_income,
        "ordinary_taxable_income": ordinary_taxable_income,
        "preferential_income": preferential_income,
        "preferential_taxable_income": preferential_taxable_income,
        "tax_before_credits": tax_before_credits,
        "child_and_dependent_credits": ctc_total,
        "child_and_dependent_credits_refundable": ctc_refundable,
        "alternative_minimum_tax": amt,
        "net_investment_income_tax": niit,
        "salt_after_cap": salt_after_cap,
        "total_tax": total_tax,
    }
