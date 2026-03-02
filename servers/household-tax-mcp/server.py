"""MCP server for US household + trust tax estimation using PolicyEngine US.

Covers quarterly estimated payments (1040-ES), self-employment tax (Schedule SE),
Schedule C deduction categorization, safe harbor calculations, trust taxation,
and combined trust/personal optimization.

AGPL-3.0 compliance: PolicyEngine US is AGPL-3.0. This server runs locally via STDIO,
so the network-use clause does not trigger. If exposed as a web service, source code
access must be provided.
"""

import math
from datetime import date, datetime
import re
from typing import Any

from mcp.server.fastmcp import FastMCP

from tax_config import (
    TAX_YEAR,
    FILING_STATUSES,
    QUARTERLY_DUE_DATES,
    SCHEDULE_C_CATEGORIES,
    SAFE_HARBOR_MULTIPLIER_HIGH_INCOME,
    SAFE_HARBOR_MULTIPLIER_STANDARD,
    SAFE_HARBOR_CURRENT_YEAR_PCT,
    HIGH_INCOME_AGI_THRESHOLD,
)

mcp = FastMCP(
    "household-tax-mcp",
    instructions=(
        "US household + trust income tax estimation server using PolicyEngine US. "
        "Computes quarterly estimated payments (1040-ES), self-employment tax "
        "(Schedule SE), Schedule C deduction categorization, safe harbor thresholds, "
        "and tax scenario comparisons. Includes trust-level taxation and combined "
        "trust/personal optimization for distribution strategy and withdrawal sequencing."
    ),
)


def _to_float(value: Any) -> float:
    """Convert PolicyEngine scalars/arrays to a numeric float."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        import numpy as np

        arr = np.asarray(value)
        if arr.size == 0:
            return 0.0
        if arr.ndim == 0:
            return float(arr.item())
        return float(arr.sum())
    except Exception:
        return float(value)


def _build_situation(
    filing_status: str,
    state: str,
    tax_year: int,
    self_employment_income: float = 0,
    w2_income: float = 0,
    capital_gains_short: float = 0,
    capital_gains_long: float = 0,
    qualified_dividends: float = 0,
    schedule_c_deductions: float = 0,
    retirement_contributions: float = 0,
    health_insurance_premiums: float = 0,
    age: int = 35,
    passive_income: float = 0,
) -> dict:
    """Build a PolicyEngine US situation dict."""
    year = str(tax_year)
    pe_status = FILING_STATUSES.get(filing_status.lower(), "SINGLE")
    # Keep the person input schema conservative: some historic variable names have
    # been removed upstream in PolicyEngine and now hard-fail parsing.
    adjusted_employment_income = max(0, w2_income + passive_income - retirement_contributions)
    adjusted_self_employment_income = max(
        0, self_employment_income - schedule_c_deductions - health_insurance_premiums
    )

    situation = {
        "people": {
            "you": {
                "age": {year: age},
                "employment_income": {year: adjusted_employment_income},
                "self_employment_income": {year: adjusted_self_employment_income},
                "short_term_capital_gains": {year: capital_gains_short},
                "long_term_capital_gains": {year: capital_gains_long},
                "qualified_dividend_income": {year: qualified_dividends},
            },
        },
        "tax_units": {
            "your_tax_unit": {
                "members": ["you"],
                "filing_status": {year: pe_status},
            },
        },
        "families": {
            "your_family": {
                "members": ["you"],
            },
        },
        "spm_units": {
            "your_spm_unit": {
                "members": ["you"],
            },
        },
        "households": {
            "your_household": {
                "members": ["you"],
                "state_name": {year: state},
            },
        },
    }
    return situation


_SCENARIO_INPUT_KEYS = {
    "self_employment_income",
    "w2_income",
    "capital_gains_short",
    "capital_gains_long",
    "qualified_dividends",
    "schedule_c_deductions",
    "retirement_contributions",
    "health_insurance_premiums",
    "age",
    "passive_income",
}


def _sanitize_scenario_input(raw: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Extract optional scenario label and keep only supported _build_situation inputs."""
    label = raw.get("scenario_name")
    if not isinstance(label, str) or not label.strip():
        alt = raw.get("name")
        if isinstance(alt, str) and alt.strip():
            label = alt.strip()
        else:
            label = None

    clean = {k: v for k, v in raw.items() if k in _SCENARIO_INPUT_KEYS}
    return label, clean


def _run_simulation(situation: dict, tax_year: int) -> dict:
    """Run PolicyEngine simulation and extract key tax figures.

    Lazy-imports PolicyEngine to avoid blocking MCP startup handshake.
    """
    from policyengine_us import Simulation
    from policyengine_core.errors.situation_parsing_error import SituationParsingError

    # Upstream PolicyEngine variable naming can change; strip unknown input variables
    # from the provided situation and retry to keep tools resilient.
    work_situation = dict(situation)
    dropped_variables: list[str] = []

    for _ in range(12):
        try:
            sim = Simulation(situation=work_situation)
            break
        except SituationParsingError as exc:
            message = str(exc)
            match = re.search(r"variable '([^']+)'", message)
            if not match:
                raise
            unknown_var = match.group(1)
            removed = False
            people = work_situation.get("people", {})
            if isinstance(people, dict):
                for person_data in people.values():
                    if isinstance(person_data, dict) and unknown_var in person_data:
                        person_data.pop(unknown_var, None)
                        removed = True
            if not removed:
                raise
            dropped_variables.append(unknown_var)
    else:
        raise RuntimeError("Unable to build PolicyEngine simulation after dropping unknown variables")

    federal_income_tax = _to_float(sim.calculate("income_tax", tax_year))
    se_tax = _to_float(sim.calculate("self_employment_tax", tax_year))
    state_income_tax = _to_float(sim.calculate("state_income_tax", tax_year))
    agi = _to_float(sim.calculate("adjusted_gross_income", tax_year))

    total_tax = federal_income_tax + se_tax + state_income_tax
    effective_rate = (total_tax / agi * 100) if agi > 0 else 0

    result = {
        "tax_year": tax_year,
        "adjusted_gross_income": round(agi, 2),
        "federal_income_tax": round(federal_income_tax, 2),
        "self_employment_tax": round(se_tax, 2),
        "state_income_tax": round(state_income_tax, 2),
        "total_tax_liability": round(total_tax, 2),
        "effective_rate_pct": round(effective_rate, 2),
    }
    if dropped_variables:
        result["dropped_unsupported_variables"] = sorted(set(dropped_variables))
    return result


def _estimate_marginal_ordinary_rate(taxable_income: float, filing_status: str) -> float:
    """Approximate federal marginal ordinary rate for planning/ordering heuristics."""
    filing = filing_status.lower()
    # Simplified 2026-ish brackets for ordering decisions (not filing-accurate output).
    if filing == "married_filing_jointly":
        brackets = [
            (23200, 0.10),
            (94300, 0.12),
            (201050, 0.22),
            (383900, 0.24),
            (487450, 0.32),
            (731200, 0.35),
            (float("inf"), 0.37),
        ]
    else:
        brackets = [
            (11600, 0.10),
            (47150, 0.12),
            (100525, 0.22),
            (191950, 0.24),
            (243725, 0.32),
            (609350, 0.35),
            (float("inf"), 0.37),
        ]

    for limit, rate in brackets:
        if taxable_income <= limit:
            return rate
    return 0.37


def _estimate_capital_gains_rate(taxable_income: float, filing_status: str) -> float:
    """Approximate LTCG rate for planning summaries."""
    filing = filing_status.lower()
    if filing == "married_filing_jointly":
        if taxable_income <= 94050:
            return 0.00
        if taxable_income <= 583750:
            return 0.15
        return 0.20

    if taxable_income <= 47025:
        return 0.00
    if taxable_income <= 518900:
        return 0.15
    return 0.20


def _estimate_state_rate(state: str) -> float:
    state = (state or "").upper()
    flat_map = {
        "CA": 0.093,
        "NY": 0.0685,
        "NJ": 0.063,
        "MA": 0.05,
        "TX": 0.0,
        "FL": 0.0,
        "WA": 0.0,
    }
    return flat_map.get(state, 0.05)


def _calculate_trust_1041_tax(
    trust_income: float,
    distributions_to_beneficiaries: float,
    trust_type: str,
    state: str,
    tax_year: int,
) -> dict[str, Any]:
    """Estimate trust-level federal+state tax with compressed brackets."""
    trust_type_norm = (trust_type or "complex").lower()

    if trust_type_norm == "grantor":
        return {
            "tax_year": tax_year,
            "trust_type": trust_type_norm,
            "trust_income": round(trust_income, 2),
            "distributions_to_beneficiaries": round(distributions_to_beneficiaries, 2),
            "dni": round(trust_income, 2),
            "taxable_income_after_distribution": 0.0,
            "federal_trust_tax": 0.0,
            "state_trust_tax": 0.0,
            "total_trust_tax": 0.0,
            "effective_trust_rate_pct": 0.0,
            "note": "Grantor trust income is generally taxed to the grantor; trust-level tax set to 0.",
        }

    dni = max(0.0, trust_income)
    taxable = max(0.0, dni - max(0.0, distributions_to_beneficiaries))

    # Compressed trust brackets (planning approximation, aligned with prior server behavior)
    brackets = [
        (3150, 0.10),
        (11450, 0.24),
        (15200, 0.35),
        (float("inf"), 0.37),
    ]

    fed_tax = 0.0
    prev = 0.0
    for limit, rate in brackets:
        if taxable <= prev:
            break
        chunk = min(taxable - prev, limit - prev)
        fed_tax += chunk * rate
        prev = limit

    state_rate = _estimate_state_rate(state)
    state_tax = taxable * state_rate
    total_tax = fed_tax + state_tax

    return {
        "tax_year": tax_year,
        "trust_type": trust_type_norm,
        "trust_income": round(trust_income, 2),
        "distributions_to_beneficiaries": round(distributions_to_beneficiaries, 2),
        "dni": round(dni, 2),
        "taxable_income_after_distribution": round(taxable, 2),
        "federal_trust_tax": round(fed_tax, 2),
        "state_trust_tax": round(state_tax, 2),
        "total_trust_tax": round(total_tax, 2),
        "effective_trust_rate_pct": round((total_tax / trust_income * 100) if trust_income > 0 else 0.0, 2),
        "state_rate_assumed": round(state_rate * 100, 2),
    }


@mcp.tool()
def estimate_quarterly_1040es(
    filing_status: str,
    state: str,
    self_employment_income: float = 0,
    w2_income: float = 0,
    capital_gains_short: float = 0,
    capital_gains_long: float = 0,
    qualified_dividends: float = 0,
    schedule_c_deductions: float = 0,
    retirement_contributions: float = 0,
    health_insurance_premiums: float = 0,
    prior_payments_ytd: float = 0,
    w2_withholding_ytd: float = 0,
    tax_year: int = TAX_YEAR,
) -> dict:
    """Estimate next quarterly payment using annualized income installment method.

    Provide YTD income figures annualized to full year. Returns total tax liability,
    amount already paid, and recommended next quarterly payment.
    """
    situation = _build_situation(
        filing_status=filing_status,
        state=state,
        tax_year=tax_year,
        self_employment_income=self_employment_income,
        w2_income=w2_income,
        capital_gains_short=capital_gains_short,
        capital_gains_long=capital_gains_long,
        qualified_dividends=qualified_dividends,
        schedule_c_deductions=schedule_c_deductions,
        retirement_contributions=retirement_contributions,
        health_insurance_premiums=health_insurance_premiums,
    )

    result = _run_simulation(situation, tax_year)

    total_paid = prior_payments_ytd + w2_withholding_ytd
    remaining_liability = max(0, result["total_tax_liability"] - total_paid)

    # Determine remaining quarters
    today = date.today()
    due_dates = QUARTERLY_DUE_DATES.get(tax_year, {})
    remaining_quarters = []
    for q, due in due_dates.items():
        if date.fromisoformat(due) > today:
            remaining_quarters.append({"quarter": q, "due_date": due})

    num_remaining = max(1, len(remaining_quarters))
    per_quarter = math.ceil(remaining_liability / num_remaining)

    result["payments_ytd"] = round(total_paid, 2)
    result["remaining_liability"] = round(remaining_liability, 2)
    result["recommended_quarterly_payment"] = per_quarter
    result["remaining_quarters"] = remaining_quarters

    return result


@mcp.tool()
def compute_schedule_se(
    net_self_employment_income: float,
    tax_year: int = TAX_YEAR,
) -> dict:
    """Compute self-employment tax (Social Security + Medicare) on Schedule SE net earnings.

    Input is net SE income (gross - Schedule C deductions).
    """
    # SE tax is 92.35% of net SE income, then 15.3% (12.4% SS + 2.9% Medicare)
    # SS cap applies; additional Medicare tax above threshold
    se_base = net_self_employment_income * 0.9235

    # 2026 SS wage base (estimated)
    ss_wage_base = 176_100
    ss_taxable = min(se_base, ss_wage_base)
    ss_tax = ss_taxable * 0.124

    medicare_tax = se_base * 0.029

    # Additional Medicare tax (0.9%) on earnings above $200k single / $250k joint
    additional_medicare = max(0, se_base - 200_000) * 0.009

    total_se_tax = ss_tax + medicare_tax + additional_medicare
    # Deductible half of SE tax
    deductible_half = total_se_tax / 2

    return {
        "tax_year": tax_year,
        "net_se_income": round(net_self_employment_income, 2),
        "se_tax_base_92_35pct": round(se_base, 2),
        "social_security_tax": round(ss_tax, 2),
        "medicare_tax": round(medicare_tax, 2),
        "additional_medicare_tax": round(additional_medicare, 2),
        "total_se_tax": round(total_se_tax, 2),
        "deductible_half_se_tax": round(deductible_half, 2),
    }


@mcp.tool()
def categorize_schedule_c_deductions(
    expenses: dict[str, float],
) -> dict:
    """Map expense categories (from Actual Budget) to Schedule C line items.

    Input: dict of {category_name: amount}. Returns categorized deductions with
    Schedule C line references and unmapped categories.
    """
    categorized = []
    unmapped = []
    total_deductions = 0.0

    for category, amount in expenses.items():
        mapping = SCHEDULE_C_CATEGORIES.get(category)
        if mapping:
            line, description = mapping
            categorized.append({
                "category": category,
                "amount": round(amount, 2),
                "schedule_c_line": line,
                "description": description,
            })
            total_deductions += amount
        else:
            unmapped.append({"category": category, "amount": round(amount, 2)})

    return {
        "categorized_deductions": categorized,
        "total_schedule_c_deductions": round(total_deductions, 2),
        "unmapped_categories": unmapped,
        "note": "Unmapped categories may still be deductible — review with tax professional.",
    }


@mcp.tool()
def project_safe_harbor(
    prior_year_tax: float,
    prior_year_agi: float,
    current_year_estimated_tax: float,
) -> dict:
    """Calculate safe harbor threshold to avoid underpayment penalty.

    Safe harbor = lower of:
    - 90% of current year tax
    - 100% of prior year tax (110% if prior year AGI > $150k)
    """
    if prior_year_agi > HIGH_INCOME_AGI_THRESHOLD:
        prior_year_threshold = prior_year_tax * SAFE_HARBOR_MULTIPLIER_HIGH_INCOME
        multiplier_used = "110%"
    else:
        prior_year_threshold = prior_year_tax * SAFE_HARBOR_MULTIPLIER_STANDARD
        multiplier_used = "100%"

    current_year_threshold = current_year_estimated_tax * SAFE_HARBOR_CURRENT_YEAR_PCT

    safe_harbor_amount = min(prior_year_threshold, current_year_threshold)
    quarterly_minimum = math.ceil(safe_harbor_amount / 4)

    return {
        "prior_year_tax": round(prior_year_tax, 2),
        "prior_year_agi": round(prior_year_agi, 2),
        "prior_year_multiplier": multiplier_used,
        "prior_year_threshold": round(prior_year_threshold, 2),
        "current_year_90pct_threshold": round(current_year_threshold, 2),
        "safe_harbor_minimum": round(safe_harbor_amount, 2),
        "quarterly_minimum_payment": quarterly_minimum,
        "note": (
            f"Pay at least ${quarterly_minimum:,}/quarter to avoid underpayment penalty. "
            f"Based on {multiplier_used} of prior year tax (${prior_year_threshold:,.0f}) "
            f"vs 90% of current year (${current_year_threshold:,.0f})."
        ),
    }


@mcp.tool()
def compare_tax_scenarios(
    filing_status: str,
    state: str,
    base_scenario: dict,
    scenarios: list[dict],
    tax_year: int = TAX_YEAR,
) -> dict:
    """Compare tax liability under different income/deduction scenarios.

    base_scenario and each scenario dict should contain keys matching
    estimate_quarterly_1040es params: self_employment_income, w2_income,
    capital_gains_short, capital_gains_long, etc.

    Returns side-by-side comparison with differences from base.
    """
    _, base_inputs = _sanitize_scenario_input(dict(base_scenario))
    base_situation = _build_situation(
        filing_status=filing_status, state=state, tax_year=tax_year, **base_inputs
    )
    base_result = _run_simulation(base_situation, tax_year)
    base_result["scenario_name"] = "Base"

    comparisons = [base_result]

    for i, scenario in enumerate(scenarios):
        scenario_copy = dict(scenario)
        label, clean_inputs = _sanitize_scenario_input(scenario_copy)
        name = label or f"Scenario {i + 1}"
        sit = _build_situation(
            filing_status=filing_status, state=state, tax_year=tax_year, **clean_inputs
        )
        result = _run_simulation(sit, tax_year)
        result["scenario_name"] = name
        result["difference_from_base"] = round(
            result["total_tax_liability"] - base_result["total_tax_liability"], 2
        )
        comparisons.append(result)

    return {
        "tax_year": tax_year,
        "filing_status": filing_status,
        "state": state,
        "scenarios": comparisons,
    }


@mcp.tool()
def generate_quarterly_vouchers(
    filing_status: str,
    state: str,
    self_employment_income: float = 0,
    w2_income: float = 0,
    capital_gains_short: float = 0,
    capital_gains_long: float = 0,
    qualified_dividends: float = 0,
    schedule_c_deductions: float = 0,
    retirement_contributions: float = 0,
    health_insurance_premiums: float = 0,
    w2_withholding_annual: float = 0,
    tax_year: int = TAX_YEAR,
) -> dict:
    """Generate 1040-ES payment amounts and due dates for all 4 quarters.

    Produces equal quarterly installments after accounting for W-2 withholding.
    """
    situation = _build_situation(
        filing_status=filing_status,
        state=state,
        tax_year=tax_year,
        self_employment_income=self_employment_income,
        w2_income=w2_income,
        capital_gains_short=capital_gains_short,
        capital_gains_long=capital_gains_long,
        qualified_dividends=qualified_dividends,
        schedule_c_deductions=schedule_c_deductions,
        retirement_contributions=retirement_contributions,
        health_insurance_premiums=health_insurance_premiums,
    )

    result = _run_simulation(situation, tax_year)

    net_liability = max(0, result["total_tax_liability"] - w2_withholding_annual)
    per_quarter = math.ceil(net_liability / 4)

    due_dates = QUARTERLY_DUE_DATES.get(tax_year, {})
    vouchers = []
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        vouchers.append({
            "quarter": q,
            "due_date": due_dates.get(q, "TBD"),
            "payment_amount": per_quarter,
        })

    return {
        **result,
        "w2_withholding_annual": round(w2_withholding_annual, 2),
        "net_estimated_tax_due": round(net_liability, 2),
        "vouchers": vouchers,
    }


@mcp.tool()
def estimate_trust_tax_1041(
    trust_income: float,
    distributions_to_beneficiaries: float = 0,
    trust_type: str = "complex",
    state: str = "NY",
    tax_year: int = TAX_YEAR,
) -> dict[str, Any]:
    """Estimate trust-level tax liability (Form 1041 style compressed bracket estimate)."""
    result = _calculate_trust_1041_tax(
        trust_income=trust_income,
        distributions_to_beneficiaries=distributions_to_beneficiaries,
        trust_type=trust_type,
        state=state,
        tax_year=tax_year,
    )
    result["model"] = "compressed_trust_brackets_planning_estimate"
    return result


@mcp.tool()
def estimate_combined_entity_tax(
    filing_status: str,
    state: str,
    personal_scenario: dict[str, Any],
    trust_scenario: dict[str, Any],
    tax_year: int = TAX_YEAR,
) -> dict[str, Any]:
    """Estimate combined personal + trust tax liability."""
    p = dict(personal_scenario)
    t = dict(trust_scenario)

    trust_distributions = float(t.get("distributions_to_beneficiaries", 0) or 0)

    personal_situation = _build_situation(
        filing_status=filing_status,
        state=state,
        tax_year=tax_year,
        self_employment_income=float(p.get("self_employment_income", 0) or 0),
        w2_income=float(p.get("w2_income", 0) or 0),
        capital_gains_short=float(p.get("capital_gains_short", 0) or 0),
        capital_gains_long=float(p.get("capital_gains_long", 0) or 0),
        qualified_dividends=float(p.get("qualified_dividends", 0) or 0),
        schedule_c_deductions=float(p.get("schedule_c_deductions", 0) or 0),
        retirement_contributions=float(p.get("retirement_contributions", 0) or 0),
        health_insurance_premiums=float(p.get("health_insurance_premiums", 0) or 0),
        passive_income=float(p.get("passive_income", 0) or 0) + trust_distributions,
    )
    personal_result = _run_simulation(personal_situation, tax_year)

    trust_result = _calculate_trust_1041_tax(
        trust_income=float(t.get("trust_income", 0) or 0),
        distributions_to_beneficiaries=trust_distributions,
        trust_type=str(t.get("trust_type", "complex")),
        state=state,
        tax_year=tax_year,
    )

    combined = round(personal_result["total_tax_liability"] + trust_result["total_trust_tax"], 2)

    return {
        "tax_year": tax_year,
        "filing_status": filing_status,
        "state": state,
        "personal_tax": personal_result,
        "trust_tax": trust_result,
        "combined_tax_liability": combined,
        "distribution_pass_through_to_personal": round(trust_distributions, 2),
    }


@mcp.tool()
def optimize_trust_personal_distributions(
    filing_status: str,
    state: str,
    personal_scenario: dict[str, Any],
    trust_scenario: dict[str, Any],
    distribution_grid: list[float] | None = None,
    tax_year: int = TAX_YEAR,
) -> dict[str, Any]:
    """Find trust distribution amount that minimizes combined trust + personal taxes."""
    trust_income = float(trust_scenario.get("trust_income", 0) or 0)

    if distribution_grid is None or len(distribution_grid) == 0:
        steps = 10
        distribution_grid = [round(trust_income * i / steps, 2) for i in range(steps + 1)]

    scenarios: list[dict[str, Any]] = []
    for amount in sorted(set(float(x) for x in distribution_grid)):
        amount = max(0.0, min(amount, trust_income))

        combined = estimate_combined_entity_tax(
            filing_status=filing_status,
            state=state,
            personal_scenario=personal_scenario,
            trust_scenario={**trust_scenario, "distributions_to_beneficiaries": amount},
            tax_year=tax_year,
        )

        scenarios.append({
            "distribution_amount": round(amount, 2),
            "combined_tax_liability": combined["combined_tax_liability"],
            "personal_tax_liability": combined["personal_tax"]["total_tax_liability"],
            "trust_tax_liability": combined["trust_tax"]["total_trust_tax"],
        })

    scenarios.sort(key=lambda x: x["combined_tax_liability"])
    best = scenarios[0] if scenarios else None

    return {
        "tax_year": tax_year,
        "filing_status": filing_status,
        "state": state,
        "trust_income": round(trust_income, 2),
        "distribution_candidates": scenarios,
        "optimal_distribution": best,
        "note": (
            "Distribution optimization is a planning estimate; include legal/trust terms and DNI constraints "
            "in implementation decisions."
        ),
    }


@mcp.tool()
def optimize_account_withdrawal_sequence(
    accounts: list[dict[str, Any]],
    withdrawal_amount: float,
    filing_status: str,
    state: str,
    tax_year: int = TAX_YEAR,
    current_age: float = 60.0,
) -> dict[str, Any]:
    """Optimize withdrawal sequence across taxable, tax-deferred, and tax-exempt wrappers."""
    if withdrawal_amount <= 0:
        return {
            "error": "withdrawal_amount must be > 0",
            "withdrawal_amount": withdrawal_amount,
        }

    ordinary_rate = _estimate_marginal_ordinary_rate(120000, filing_status)
    cap_gains_rate = _estimate_capital_gains_rate(120000, filing_status)
    state_rate = _estimate_state_rate(state)

    def tax_rate_for_account(acct: dict[str, Any]) -> float:
        wrapper = str(acct.get("tax_wrapper", "taxable")).lower()
        gain_ratio = float(acct.get("estimated_gain_ratio", 0.5) or 0.5)

        if wrapper == "tax_exempt":
            return 0.0
        if wrapper == "tax_deferred":
            penalty = 0.10 if current_age < 59.5 else 0.0
            return ordinary_rate + state_rate + penalty

        # taxable
        return max(0.0, gain_ratio) * (cap_gains_rate + state_rate)

    ranked = sorted(
        accounts,
        key=lambda a: tax_rate_for_account(a),
    )

    remaining = withdrawal_amount
    plan = []
    total_estimated_tax = 0.0
    gross_withdrawn = 0.0

    for acct in ranked:
        if remaining <= 0:
            break
        balance = float(acct.get("balance", 0) or 0)
        if balance <= 0:
            continue

        amount = min(balance, remaining)
        rate = tax_rate_for_account(acct)
        estimated_tax = amount * rate
        total_estimated_tax += estimated_tax
        gross_withdrawn += amount
        remaining -= amount

        plan.append({
            "account_id": acct.get("account_id"),
            "name": acct.get("name"),
            "tax_wrapper": acct.get("tax_wrapper"),
            "account_type": acct.get("account_type"),
            "withdraw_amount": round(amount, 2),
            "estimated_tax_rate": round(rate * 100, 2),
            "estimated_tax": round(estimated_tax, 2),
        })

    return {
        "tax_year": tax_year,
        "filing_status": filing_status,
        "state": state,
        "withdrawal_amount_requested": round(withdrawal_amount, 2),
        "withdrawal_amount_planned": round(gross_withdrawn, 2),
        "shortfall": round(max(0.0, remaining), 2),
        "estimated_total_tax": round(total_estimated_tax, 2),
        "estimated_after_tax_proceeds": round(gross_withdrawn - total_estimated_tax, 2),
        "withdrawal_plan": plan,
        "assumptions": {
            "ordinary_rate_pct": round(ordinary_rate * 100, 2),
            "capital_gains_rate_pct": round(cap_gains_rate * 100, 2),
            "state_rate_pct": round(state_rate * 100, 2),
            "early_withdrawal_penalty_applied": current_age < 59.5,
        },
    }


@mcp.tool()
def estimate_quarterly_payments_combined(
    filing_status: str,
    state: str,
    personal_scenario: dict[str, Any],
    trust_scenario: dict[str, Any],
    prior_payments_ytd: float = 0,
    w2_withholding_ytd: float = 0,
    tax_year: int = TAX_YEAR,
) -> dict[str, Any]:
    """Estimate next quarterly payment including combined personal + trust liability."""
    combined = estimate_combined_entity_tax(
        filing_status=filing_status,
        state=state,
        personal_scenario=personal_scenario,
        trust_scenario=trust_scenario,
        tax_year=tax_year,
    )

    combined_liability = float(combined["combined_tax_liability"])
    paid = float(prior_payments_ytd + w2_withholding_ytd)
    remaining_liability = max(0.0, combined_liability - paid)

    today = date.today()
    due_dates = QUARTERLY_DUE_DATES.get(tax_year, {})
    remaining_quarters = [
        {"quarter": q, "due_date": due}
        for q, due in due_dates.items()
        if date.fromisoformat(due) > today
    ]

    n = max(1, len(remaining_quarters))
    recommended = math.ceil(remaining_liability / n)

    return {
        "tax_year": tax_year,
        "filing_status": filing_status,
        "state": state,
        "combined_tax_liability": round(combined_liability, 2),
        "payments_ytd": round(paid, 2),
        "remaining_liability": round(remaining_liability, 2),
        "recommended_quarterly_payment": recommended,
        "remaining_quarters": remaining_quarters,
        "personal_tax_liability": combined["personal_tax"]["total_tax_liability"],
        "trust_tax_liability": combined["trust_tax"]["total_trust_tax"],
        "distribution_assumption": combined["distribution_pass_through_to_personal"],
    }


if __name__ == "__main__":
    mcp.run()
