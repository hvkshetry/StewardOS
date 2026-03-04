"""household-tax-mcp v2: scenario-first tax planning engine.

This is a breaking redesign with no backward compatibility.
Primary focus:
- household + trust decision analysis
- hard-coded scenario catalog for common complex-return decisions
- MA active forward modeling; NY retained for historical provenance only

AGPL note: this server depends on policyengine-us (AGPL-3.0).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

from tax_config import (
    ACTIVE_FORWARD_STATES,
    DEFAULT_HORIZON_YEARS,
    DEFAULT_OBJECTIVE,
    DEFAULT_PORTFOLIO_RETURN,
    DEFAULT_STARTING_NET_WORTH,
    FILING_STATUSES,
    MA_EFFECTIVE_RATE,
    MAX_HORIZON_YEARS,
    MIN_HORIZON_YEARS,
    NIIT_RATE,
    READINESS_COMPLEX_MANUAL_FORMS,
    READINESS_SUPPORTED_FORMS,
    SCENARIO_DEFINITIONS,
    STRATEGY_GROUPS,
    SUPPORTED_OBJECTIVES,
    TAX_YEAR,
    TRUST_BRACKETS,
)

mcp = FastMCP(
    "household-tax-mcp",
    instructions=(
        "Scenario-first household and trust tax planning engine. "
        "Performs strategy comparisons, optimization, estimated payment plans, "
        "and filing readiness checks using a hard-coded scenario catalog."
    ),
)

# In-memory stores for v2 runtime sessions.
RETURN_STORE: dict[str, dict[str, Any]] = {}
PROFILE_STORE: dict[str, dict[str, Any]] = {}
RUN_STORE: dict[str, dict[str, Any]] = {}
PLAN_STORE: dict[str, dict[str, Any]] = {}

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_REQUIRED = os.environ.get("HOUSEHOLD_TAX_REQUIRE_DATABASE", "false").strip().lower() in {"1", "true", "yes"}
_DB_READY = False


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _db_enabled() -> bool:
    return bool(DATABASE_URL) and psycopg is not None


def _db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    if psycopg is None:
        raise RuntimeError("psycopg is required for database persistence")
    return psycopg.connect(DATABASE_URL, autocommit=True)


def _db_init() -> None:
    global _DB_READY
    if _DB_READY:
        return

    if DB_REQUIRED and not _db_enabled():
        raise RuntimeError("Database persistence is required but DATABASE_URL/psycopg is not available")
    if not _db_enabled():
        return

    ddl = """
    CREATE SCHEMA IF NOT EXISTS tax;

    CREATE TABLE IF NOT EXISTS tax.business_profiles (
      profile_id TEXT PRIMARY KEY,
      profile JSONB NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax.return_facts (
      return_id TEXT PRIMARY KEY,
      year INT NOT NULL,
      entity_type TEXT NOT NULL,
      source_path TEXT NOT NULL,
      forms_detected JSONB NOT NULL,
      schedules_detected JSONB NOT NULL,
      jurisdictions_detected JSONB NOT NULL,
      manual_review_flags JSONB NOT NULL,
      extracted_text_hash TEXT NOT NULL,
      ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax.scenario_runs (
      run_id TEXT PRIMARY KEY,
      scenario_id TEXT NOT NULL,
      scenario_name TEXT NOT NULL,
      objective TEXT NOT NULL,
      horizon_years INT NOT NULL,
      state TEXT NOT NULL,
      tax_year INT NOT NULL,
      active_jurisdictions JSONB NOT NULL,
      assumptions JSONB NOT NULL,
      inputs JSONB NOT NULL,
      recommended_strategy_id TEXT NOT NULL,
      estimated_payments_plan_id TEXT NOT NULL,
      result JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax.scenario_results (
      id BIGSERIAL PRIMARY KEY,
      run_id TEXT NOT NULL REFERENCES tax.scenario_runs(run_id) ON DELETE CASCADE,
      rank INT NOT NULL,
      strategy_id TEXT NOT NULL,
      label TEXT NOT NULL,
      annual_tax NUMERIC(18,2) NOT NULL DEFAULT 0,
      annual_financing_cost NUMERIC(18,2) NOT NULL DEFAULT 0,
      annual_penalty NUMERIC(18,2) NOT NULL DEFAULT 0,
      annual_after_tax_cash NUMERIC(18,2) NOT NULL DEFAULT 0,
      ending_net_worth NUMERIC(18,2) NOT NULL DEFAULT 0,
      total_economic_cost NUMERIC(18,2) NOT NULL DEFAULT 0,
      payroll_tax NUMERIC(18,2) NOT NULL DEFAULT 0,
      se_tax NUMERIC(18,2) NOT NULL DEFAULT 0,
      qbi_deduction NUMERIC(18,2) NOT NULL DEFAULT 0,
      qbi_tax_shield NUMERIC(18,2) NOT NULL DEFAULT 0,
      components JSONB NOT NULL,
      tax_totals JSONB NOT NULL,
      qbi_effects JSONB NOT NULL,
      retirement_effects JSONB NOT NULL,
      cashflow_effects JSONB NOT NULL,
      estimated_payment_implications JSONB NOT NULL,
      trajectory JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax.estimated_payment_plans (
      plan_id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL,
      scenario_id TEXT NOT NULL,
      plan JSONB NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax.compensation_strategies (
      id BIGSERIAL PRIMARY KEY,
      run_id TEXT NOT NULL REFERENCES tax.scenario_runs(run_id) ON DELETE CASCADE,
      strategy_id TEXT NOT NULL,
      business_structure TEXT NOT NULL,
      w2_compensation NUMERIC(18,2) NOT NULL DEFAULT 0,
      distribution_income NUMERIC(18,2) NOT NULL DEFAULT 0,
      guaranteed_payments NUMERIC(18,2) NOT NULL DEFAULT 0,
      payroll_tax NUMERIC(18,2) NOT NULL DEFAULT 0,
      se_tax NUMERIC(18,2) NOT NULL DEFAULT 0,
      qbi_deduction NUMERIC(18,2) NOT NULL DEFAULT 0,
      qbi_tax_shield NUMERIC(18,2) NOT NULL DEFAULT 0,
      total_tax NUMERIC(18,2) NOT NULL DEFAULT 0,
      annual_after_tax_cash NUMERIC(18,2) NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS tax.retirement_elections (
      id BIGSERIAL PRIMARY KEY,
      run_id TEXT NOT NULL REFERENCES tax.scenario_runs(run_id) ON DELETE CASCADE,
      strategy_id TEXT NOT NULL,
      plan TEXT NOT NULL,
      contribution NUMERIC(18,2) NOT NULL DEFAULT 0,
      tax_deferral_value NUMERIC(18,2) NOT NULL DEFAULT 0,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
    _DB_READY = True


def _db_execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    if not _db_enabled():
        return
    _db_init()
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def _db_fetchall(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not _db_enabled():
        return []
    _db_init()
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [c.name for c in cur.description] if cur.description else []
    return [{cols[i]: row[i] for i in range(len(cols))} for row in rows]


def _db_fetchone(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = _db_fetchall(sql, params)
    return rows[0] if rows else None


def _persist_profile(payload: dict[str, Any]) -> None:
    _db_execute(
        """
        INSERT INTO tax.business_profiles(profile_id, profile, updated_at)
        VALUES (%s, %s::jsonb, NOW())
        ON CONFLICT (profile_id)
        DO UPDATE SET profile = EXCLUDED.profile, updated_at = NOW()
        """,
        (payload["profile_id"], _json_dumps(payload)),
    )


def _persist_return(record: dict[str, Any]) -> None:
    _db_execute(
        """
        INSERT INTO tax.return_facts(
            return_id, year, entity_type, source_path, forms_detected,
            schedules_detected, jurisdictions_detected, manual_review_flags,
            extracted_text_hash, ingested_at
        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW())
        ON CONFLICT (return_id) DO UPDATE SET
            forms_detected = EXCLUDED.forms_detected,
            schedules_detected = EXCLUDED.schedules_detected,
            jurisdictions_detected = EXCLUDED.jurisdictions_detected,
            manual_review_flags = EXCLUDED.manual_review_flags,
            extracted_text_hash = EXCLUDED.extracted_text_hash
        """,
        (
            record["return_id"],
            int(record["year"]),
            record["entity_type"],
            record["source_path"],
            _json_dumps(record["forms_detected"]),
            _json_dumps(record["schedules_detected"]),
            _json_dumps(record["jurisdictions_detected"]),
            _json_dumps(record["manual_review_flags"]),
            record["extracted_text_hash"],
        ),
    )


def _persist_plan(plan: dict[str, Any]) -> None:
    _db_execute(
        """
        INSERT INTO tax.estimated_payment_plans(plan_id, run_id, scenario_id, plan, created_at)
        VALUES (%s, %s, %s, %s::jsonb, NOW())
        ON CONFLICT (plan_id) DO UPDATE SET plan = EXCLUDED.plan
        """,
        (plan["plan_id"], plan["run_id"], plan["scenario_id"], _json_dumps(plan)),
    )


def _persist_run(result: dict[str, Any], inputs: dict[str, Any], assumptions: dict[str, Any]) -> None:
    _db_execute(
        """
        INSERT INTO tax.scenario_runs(
            run_id, scenario_id, scenario_name, objective, horizon_years, state, tax_year,
            active_jurisdictions, assumptions, inputs, recommended_strategy_id,
            estimated_payments_plan_id, result, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, NOW())
        ON CONFLICT (run_id) DO UPDATE SET result = EXCLUDED.result
        """,
        (
            result["run_id"],
            result["scenario_id"],
            result["scenario_name"],
            result["objective"],
            int(result["horizon_years"]),
            result["state"],
            int(result["tax_year"]),
            _json_dumps(["US", result["state"]]),
            _json_dumps(assumptions),
            _json_dumps(inputs),
            result["recommended"]["strategy_id"],
            result["estimated_payments_plan_id"],
            _json_dumps(result),
        ),
    )

    _db_execute("DELETE FROM tax.scenario_results WHERE run_id = %s", (result["run_id"],))
    _db_execute("DELETE FROM tax.compensation_strategies WHERE run_id = %s", (result["run_id"],))
    _db_execute("DELETE FROM tax.retirement_elections WHERE run_id = %s", (result["run_id"],))

    for alt in result.get("alternatives", []):
        tax_totals = alt.get("tax_totals") or {}
        qbi_effects = alt.get("qbi_effects") or {}
        retirement = alt.get("retirement_effects") or {}
        cashflow = alt.get("cashflow_effects") or {}
        payments = alt.get("estimated_payment_implications") or {}

        _db_execute(
            """
            INSERT INTO tax.scenario_results(
                run_id, rank, strategy_id, label, annual_tax, annual_financing_cost, annual_penalty,
                annual_after_tax_cash, ending_net_worth, total_economic_cost, payroll_tax, se_tax,
                qbi_deduction, qbi_tax_shield, components, tax_totals, qbi_effects, retirement_effects,
                cashflow_effects, estimated_payment_implications, trajectory, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, NOW())
            """,
            (
                result["run_id"],
                int(alt.get("rank") or 0),
                alt.get("strategy_id", ""),
                alt.get("label", ""),
                _round2(_as_float(alt.get("annual_tax"))),
                _round2(_as_float(alt.get("annual_financing_cost"))),
                _round2(_as_float(alt.get("annual_penalty"))),
                _round2(_as_float(alt.get("annual_after_tax_cash"))),
                _round2(_as_float(alt.get("ending_net_worth"))),
                _round2(_as_float(alt.get("total_economic_cost"))),
                _round2(_as_float(tax_totals.get("payroll_tax"))),
                _round2(_as_float(tax_totals.get("self_employment_tax"))),
                _round2(_as_float(qbi_effects.get("qbi_deduction"))),
                _round2(_as_float(qbi_effects.get("qbi_tax_shield"))),
                _json_dumps(alt.get("components") or {}),
                _json_dumps(tax_totals),
                _json_dumps(qbi_effects),
                _json_dumps(retirement),
                _json_dumps(cashflow),
                _json_dumps(payments),
                _json_dumps(alt.get("trajectory") or []),
            ),
        )

        if result.get("scenario_id") == "business_owner_compensation_and_retirement_election_strategy":
            _db_execute(
                """
                INSERT INTO tax.compensation_strategies(
                    run_id, strategy_id, business_structure, w2_compensation, distribution_income,
                    guaranteed_payments, payroll_tax, se_tax, qbi_deduction, qbi_tax_shield,
                    total_tax, annual_after_tax_cash, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    result["run_id"],
                    alt.get("strategy_id", ""),
                    alt.get("components", {}).get("business_structure", ""),
                    _round2(_as_float(alt.get("components", {}).get("w2_compensation"))),
                    _round2(_as_float(alt.get("components", {}).get("distribution_income"))),
                    _round2(_as_float(alt.get("components", {}).get("guaranteed_payments"))),
                    _round2(_as_float(tax_totals.get("payroll_tax"))),
                    _round2(_as_float(tax_totals.get("self_employment_tax"))),
                    _round2(_as_float(qbi_effects.get("qbi_deduction"))),
                    _round2(_as_float(qbi_effects.get("qbi_tax_shield"))),
                    _round2(_as_float(alt.get("annual_tax"))),
                    _round2(_as_float(alt.get("annual_after_tax_cash"))),
                ),
            )
            _db_execute(
                """
                INSERT INTO tax.retirement_elections(
                    run_id, strategy_id, plan, contribution, tax_deferral_value, created_at
                ) VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    result["run_id"],
                    alt.get("strategy_id", ""),
                    alt.get("retirement_effects", {}).get("plan", ""),
                    _round2(_as_float(alt.get("retirement_effects", {}).get("contribution"))),
                    _round2(_as_float(alt.get("retirement_effects", {}).get("tax_deferral_value"))),
                ),
            )


def _load_plan(plan_id: str) -> dict[str, Any] | None:
    row = _db_fetchone("SELECT plan FROM tax.estimated_payment_plans WHERE plan_id = %s", (plan_id,))
    if not row:
        return None
    return _json_loads(row.get("plan"))


def _load_run(run_id: str) -> dict[str, Any] | None:
    row = _db_fetchone("SELECT result FROM tax.scenario_runs WHERE run_id = %s", (run_id,))
    if not row:
        return None
    return _json_loads(row.get("result"))


def _load_returns(year: int, entity_type: str) -> list[dict[str, Any]]:
    rows = _db_fetchall(
        """
        SELECT return_id, year, entity_type, source_path, forms_detected, schedules_detected,
               jurisdictions_detected, manual_review_flags, extracted_text_hash, ingested_at
        FROM tax.return_facts
        WHERE year = %s AND entity_type = %s
        ORDER BY ingested_at DESC
        """,
        (int(year), entity_type),
    )
    out = []
    for r in rows:
        out.append(
            {
                "return_id": r.get("return_id"),
                "year": int(r.get("year") or 0),
                "entity_type": r.get("entity_type"),
                "source_path": r.get("source_path"),
                "forms_detected": _json_loads(r.get("forms_detected")) or [],
                "schedules_detected": _json_loads(r.get("schedules_detected")) or [],
                "jurisdictions_detected": _json_loads(r.get("jurisdictions_detected")) or [],
                "manual_review_flags": _json_loads(r.get("manual_review_flags")) or [],
                "extracted_text_hash": r.get("extracted_text_hash"),
                "ingested_at": str(r.get("ingested_at")),
            }
        )
    return out


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _round2(value: float) -> float:
    return round(float(value), 2)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return default


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


def _objective_name(value: str | None) -> str:
    candidate = (value or DEFAULT_OBJECTIVE).strip().lower()
    if candidate not in SUPPORTED_OBJECTIVES:
        allowed = ", ".join(sorted(SUPPORTED_OBJECTIVES))
        raise ValueError(f"Unsupported objective '{candidate}'. Supported: {allowed}")
    return candidate


def _normalize_horizon(horizon_years: Any | None) -> int:
    if horizon_years is None:
        return DEFAULT_HORIZON_YEARS
    years = int(horizon_years)
    if years < MIN_HORIZON_YEARS or years > MAX_HORIZON_YEARS:
        raise ValueError(
            f"horizon_years must be in [{MIN_HORIZON_YEARS}, {MAX_HORIZON_YEARS}]"
        )
    return years


def _active_state_from_inputs(inputs: dict[str, Any], assumptions: dict[str, Any]) -> str:
    state = str(inputs.get("state") or assumptions.get("state") or "MA").upper()
    if state not in ACTIVE_FORWARD_STATES:
        allowed = ", ".join(sorted(ACTIVE_FORWARD_STATES))
        raise ValueError(
            f"Forward projections support active states: {allowed}. "
            f"State '{state}' can only be used as historical context."
        )
    return state


def _assumptions(assumptions: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(assumptions or {})
    payload.setdefault("objective", DEFAULT_OBJECTIVE)
    payload.setdefault("horizon_years", DEFAULT_HORIZON_YEARS)
    payload.setdefault("starting_net_worth", DEFAULT_STARTING_NET_WORTH)
    payload.setdefault("portfolio_return", DEFAULT_PORTFOLIO_RETURN)
    payload.setdefault("state", "MA")
    payload["objective"] = _objective_name(payload.get("objective"))
    payload["horizon_years"] = _normalize_horizon(payload.get("horizon_years"))
    payload["starting_net_worth"] = _as_float(payload.get("starting_net_worth"), DEFAULT_STARTING_NET_WORTH)
    payload["portfolio_return"] = _as_float(payload.get("portfolio_return"), DEFAULT_PORTFOLIO_RETURN)
    return payload


def _extract_text(source_path: str) -> str:
    path = Path(source_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"source_path does not exist: {path}")

    if path.suffix.lower() in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")

    if path.suffix.lower() == ".pdf":
        try:
            return subprocess.check_output(
                ["pdftotext", "-layout", str(path), "-"],
                text=True,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("pdftotext is required for PDF ingestion") from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() if exc.stderr else "unknown error"
            raise RuntimeError(f"pdftotext failed: {message}") from exc

    raise ValueError("Unsupported source format. Use .txt/.md/.pdf")


def _detect_forms(text: str) -> list[str]:
    forms = set(re.findall(r"\bForm\s+([0-9]{3,4}[A-Z0-9-]*)\b", text, flags=re.IGNORECASE))
    return sorted(x.upper() for x in forms)


def _detect_schedules(text: str) -> list[str]:
    schedules = set(re.findall(r"\bSchedule\s+([A-Z0-9-]+)\b", text, flags=re.IGNORECASE))
    return sorted(x.upper() for x in schedules)


def _detect_jurisdictions(text: str) -> list[str]:
    hit = set()
    upper = text.upper()
    if "MASSACHUSETTS" in upper or "M-" in upper:
        hit.add("MA")
    if "NEW YORK" in upper or "IT-203" in upper or "IT-201" in upper:
        hit.add("NY")
    if "FL" in upper or "FLORIDA" in upper:
        hit.add("FL")
    if "FEDERAL" in upper or "FORM 1040" in upper or "FORM 1041" in upper:
        hit.add("US")
    return sorted(hit)


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
    passive_income: float = 0,
    age: int = 45,
) -> dict[str, Any]:
    year = str(tax_year)
    pe_status = FILING_STATUSES.get(filing_status.lower(), "JOINT")

    adjusted_wages = max(0.0, w2_income + passive_income - retirement_contributions)
    adjusted_se = max(
        0.0,
        self_employment_income - schedule_c_deductions - health_insurance_premiums,
    )

    return {
        "people": {
            "you": {
                "age": {year: age},
                "employment_income": {year: adjusted_wages},
                "self_employment_income": {year: adjusted_se},
                "short_term_capital_gains": {year: max(0.0, capital_gains_short)},
                "long_term_capital_gains": {year: max(0.0, capital_gains_long)},
                "qualified_dividend_income": {year: max(0.0, qualified_dividends)},
            }
        },
        "tax_units": {
            "your_tax_unit": {
                "members": ["you"],
                "filing_status": {year: pe_status},
            }
        },
        "families": {"your_family": {"members": ["you"]}},
        "spm_units": {"your_spm_unit": {"members": ["you"]}},
        "households": {
            "your_household": {
                "members": ["you"],
                "state_name": {year: state},
            }
        },
    }


def _estimate_marginal_ordinary_rate(taxable_income: float, filing_status: str) -> float:
    filing = filing_status.lower()
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


def _capital_gains_rate(taxable_income: float, filing_status: str) -> float:
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


def _estimate_se_tax(net_self_employment_income: float, filing_status: str) -> float:
    se_base = max(0.0, net_self_employment_income) * 0.9235
    ss_wage_base = 176_100
    ss_tax = min(se_base, ss_wage_base) * 0.124
    medicare_tax = se_base * 0.029

    addl_threshold = 250_000 if filing_status.lower() == "married_filing_jointly" else 200_000
    addl_medicare = max(0.0, se_base - addl_threshold) * 0.009
    return ss_tax + medicare_tax + addl_medicare


def _run_personal_projection(
    inputs: dict[str, Any],
    state: str,
    tax_year: int,
) -> dict[str, Any]:
    filing_status = str(inputs.get("filing_status", "married_filing_jointly"))
    situation = _build_situation(
        filing_status=filing_status,
        state=state,
        tax_year=tax_year,
        self_employment_income=_as_float(inputs.get("self_employment_income")),
        w2_income=_as_float(inputs.get("w2_income")),
        capital_gains_short=_as_float(inputs.get("capital_gains_short")),
        capital_gains_long=_as_float(inputs.get("capital_gains_long")),
        qualified_dividends=_as_float(inputs.get("qualified_dividends")),
        schedule_c_deductions=_as_float(inputs.get("schedule_c_deductions")),
        retirement_contributions=_as_float(inputs.get("retirement_contributions")),
        health_insurance_premiums=_as_float(inputs.get("health_insurance_premiums")),
        passive_income=_as_float(inputs.get("passive_income")),
        age=int(inputs.get("age", 45) or 45),
    )

    try:
        from policyengine_us import Simulation
        from policyengine_core.errors.situation_parsing_error import SituationParsingError

        work_situation = dict(situation)
        for _ in range(8):
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
                for pdata in work_situation.get("people", {}).values():
                    if isinstance(pdata, dict) and unknown_var in pdata:
                        pdata.pop(unknown_var, None)
                        removed = True
                if not removed:
                    raise
        else:
            raise RuntimeError("Unable to instantiate PolicyEngine simulation")

        federal_income_tax = _to_float(sim.calculate("income_tax", tax_year))
        se_tax = _to_float(sim.calculate("self_employment_tax", tax_year))
        state_income_tax = _to_float(sim.calculate("state_income_tax", tax_year))
        agi = _to_float(sim.calculate("adjusted_gross_income", tax_year))
        total = federal_income_tax + se_tax + state_income_tax
        return {
            "model": "policyengine-us",
            "tax_year": tax_year,
            "adjusted_gross_income": _round2(agi),
            "federal_income_tax": _round2(federal_income_tax),
            "self_employment_tax": _round2(se_tax),
            "state_income_tax": _round2(state_income_tax),
            "total_tax_liability": _round2(total),
            "effective_rate_pct": _round2((total / agi * 100) if agi > 0 else 0.0),
        }
    except Exception:
        wages = _as_float(inputs.get("w2_income")) + _as_float(inputs.get("passive_income"))
        se_income = max(0.0, _as_float(inputs.get("self_employment_income")) - _as_float(inputs.get("schedule_c_deductions")))
        cap_st = _as_float(inputs.get("capital_gains_short"))
        cap_lt = _as_float(inputs.get("capital_gains_long"))
        qdiv = _as_float(inputs.get("qualified_dividends"))
        retirement = _as_float(inputs.get("retirement_contributions"))
        health = _as_float(inputs.get("health_insurance_premiums"))

        agi = max(0.0, wages + se_income + cap_st + cap_lt + qdiv - retirement - health)
        ordinary_estimate = max(0.0, wages + se_income + cap_st - retirement - health)
        ord_rate = _estimate_marginal_ordinary_rate(ordinary_estimate, filing_status)
        cap_rate = _capital_gains_rate(agi, filing_status)

        federal_income_tax = ordinary_estimate * ord_rate + (cap_lt + qdiv) * cap_rate
        se_tax = _estimate_se_tax(se_income, filing_status)
        state_income_tax = agi * MA_EFFECTIVE_RATE
        total = federal_income_tax + se_tax + state_income_tax
        return {
            "model": "fallback-estimator",
            "tax_year": tax_year,
            "adjusted_gross_income": _round2(agi),
            "federal_income_tax": _round2(federal_income_tax),
            "self_employment_tax": _round2(se_tax),
            "state_income_tax": _round2(state_income_tax),
            "total_tax_liability": _round2(total),
            "effective_rate_pct": _round2((total / agi * 100) if agi > 0 else 0.0),
        }


def _estimate_trust_tax(
    ordinary_income: float,
    qualified_dividends: float,
    long_term_capital_gains: float,
    distribution_ratio: float,
    trust_type: str,
) -> dict[str, Any]:
    trust_type_norm = str(trust_type or "complex").lower()
    ordinary_income = max(0.0, ordinary_income)
    qualified_dividends = max(0.0, qualified_dividends)
    long_term_capital_gains = max(0.0, long_term_capital_gains)

    gross_income = ordinary_income + qualified_dividends + long_term_capital_gains
    ratio = max(0.0, min(1.0, distribution_ratio))
    distributed_income = gross_income * ratio

    if trust_type_norm == "grantor":
        return {
            "trust_type": "grantor",
            "dni": _round2(gross_income),
            "distributed_income": _round2(distributed_income),
            "trust_taxable_ordinary": 0.0,
            "trust_taxable_preferential": 0.0,
            "federal_trust_tax": 0.0,
            "state_trust_tax": 0.0,
            "niit": 0.0,
            "total_trust_tax": 0.0,
        }

    retained_ordinary = ordinary_income * (1.0 - ratio)
    retained_preferential = (qualified_dividends + long_term_capital_gains) * (1.0 - ratio)

    fed_ordinary_tax = 0.0
    prev = 0.0
    for limit, rate in TRUST_BRACKETS:
        if retained_ordinary <= prev:
            break
        chunk = min(retained_ordinary - prev, limit - prev)
        fed_ordinary_tax += chunk * rate
        prev = limit

    fed_pref_tax = retained_preferential * 0.20
    niit_base = max(0.0, retained_preferential + max(0.0, retained_ordinary - 15_200.0))
    niit = niit_base * NIIT_RATE
    state_tax = (retained_ordinary + retained_preferential) * MA_EFFECTIVE_RATE

    total = fed_ordinary_tax + fed_pref_tax + niit + state_tax
    return {
        "trust_type": trust_type_norm,
        "dni": _round2(gross_income),
        "distributed_income": _round2(distributed_income),
        "trust_taxable_ordinary": _round2(retained_ordinary),
        "trust_taxable_preferential": _round2(retained_preferential),
        "federal_trust_tax": _round2(fed_ordinary_tax + fed_pref_tax),
        "state_trust_tax": _round2(state_tax),
        "niit": _round2(niit),
        "total_trust_tax": _round2(total),
    }


def _allocate_distribution(
    distribution_amount: float,
    ordinary_income: float,
    qualified_dividends: float,
    long_term_capital_gains: float,
    order: tuple[str, ...],
) -> dict[str, float]:
    remaining = max(0.0, distribution_amount)
    buckets = {
        "ordinary": max(0.0, ordinary_income),
        "qualified_dividends": max(0.0, qualified_dividends),
        "long_term_capital_gains": max(0.0, long_term_capital_gains),
    }
    out = {k: 0.0 for k in buckets}

    for key in order:
        if remaining <= 0:
            break
        take = min(remaining, buckets[key])
        out[key] = take
        remaining -= take

    return out


def _simulate_net_worth(
    annual_tax: float,
    annual_financing_cost: float,
    annual_penalty: float,
    annual_after_tax_cash: float,
    assumptions: dict[str, Any],
    horizon_years: int,
    one_time_tax: float = 0.0,
    one_time_financing_cost: float = 0.0,
    one_time_penalty: float = 0.0,
    one_time_cashflow: float = 0.0,
) -> dict[str, Any]:
    net_worth = _as_float(assumptions.get("starting_net_worth"), DEFAULT_STARTING_NET_WORTH)
    growth_rate = _as_float(assumptions.get("portfolio_return"), DEFAULT_PORTFOLIO_RETURN)
    start_year = int(assumptions.get("tax_year", TAX_YEAR) or TAX_YEAR)

    trajectory = []
    total_economic_cost = 0.0

    for idx in range(horizon_years):
        year = start_year + idx
        tax = annual_tax
        financing = annual_financing_cost
        penalty = annual_penalty
        cash = annual_after_tax_cash

        if idx == 0:
            tax += one_time_tax
            financing += one_time_financing_cost
            penalty += one_time_penalty
            cash += one_time_cashflow

        total_economic_cost += tax + financing + penalty
        net_worth = net_worth * (1.0 + growth_rate) + cash - tax - financing - penalty
        trajectory.append(
            {
                "year": year,
                "ending_net_worth": _round2(net_worth),
                "tax": _round2(tax),
                "financing_cost": _round2(financing),
                "penalty": _round2(penalty),
                "after_tax_cashflow": _round2(cash),
            }
        )

    return {
        "starting_net_worth": _round2(_as_float(assumptions.get("starting_net_worth"), DEFAULT_STARTING_NET_WORTH)),
        "ending_net_worth": _round2(net_worth),
        "total_economic_cost": _round2(total_economic_cost),
        "trajectory": trajectory,
    }


def _base_personal_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "filing_status": str(inputs.get("filing_status", "married_filing_jointly")),
        "w2_income": _as_float(inputs.get("w2_income")),
        "self_employment_income": _as_float(inputs.get("self_employment_income")),
        "capital_gains_short": _as_float(inputs.get("capital_gains_short")),
        "capital_gains_long": _as_float(inputs.get("capital_gains_long")),
        "qualified_dividends": _as_float(inputs.get("qualified_dividends")),
        "schedule_c_deductions": _as_float(inputs.get("schedule_c_deductions")),
        "retirement_contributions": _as_float(inputs.get("retirement_contributions")),
        "health_insurance_premiums": _as_float(inputs.get("health_insurance_premiums")),
        "passive_income": _as_float(inputs.get("passive_income")),
        "age": int(inputs.get("age", 45) or 45),
    }


def _evaluate_trust_distribute_vs_retain(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    trust_type = str(inputs.get("trust_type", "complex"))
    t_ord = _as_float(inputs.get("trust_income_ordinary"))
    t_qdiv = _as_float(inputs.get("trust_income_qualified_dividends"))
    t_ltcg = _as_float(inputs.get("trust_income_long_term_capital_gains"))
    total_trust_income = t_ord + t_qdiv + t_ltcg

    grid = inputs.get("distribution_grid") or [0.0, 0.25, 0.5, 0.75, 1.0]
    ratios = sorted({max(0.0, min(1.0, _as_float(x))) for x in grid})

    alternatives = []
    for ratio in ratios:
        trust = _estimate_trust_tax(t_ord, t_qdiv, t_ltcg, ratio, trust_type)

        personal = dict(personal_base)
        personal["passive_income"] = personal["passive_income"] + t_ord * ratio
        personal["qualified_dividends"] = personal["qualified_dividends"] + t_qdiv * ratio
        personal["capital_gains_long"] = personal["capital_gains_long"] + t_ltcg * ratio
        personal_out = _run_personal_projection(personal, state, int(assumptions.get("tax_year", TAX_YEAR)))

        annual_tax = personal_out["total_tax_liability"] + trust["total_trust_tax"]
        alternatives.append(
            {
                "strategy_id": f"distribution_{int(ratio * 100)}pct",
                "label": f"Distribute {int(ratio * 100)}% of trust income",
                "distribution_ratio": ratio,
                "distribution_amount": _round2(total_trust_income * ratio),
                "annual_tax": _round2(annual_tax),
                "annual_financing_cost": 0.0,
                "annual_penalty": 0.0,
                "annual_after_tax_cash": _as_float(inputs.get("annual_savings"), 0.0),
                "components": {
                    "personal_tax": personal_out,
                    "trust_tax": trust,
                },
            }
        )

    return alternatives


def _evaluate_trust_distribution_timing(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    base = _evaluate_trust_distribute_vs_retain(inputs, assumptions, state)
    target_ratio = max(0.0, min(1.0, _as_float(inputs.get("target_distribution_ratio"), 0.5)))

    reference = min(base, key=lambda x: abs(x["distribution_ratio"] - target_ratio))
    amount = reference["distribution_amount"]
    base_tax = reference["annual_tax"]

    options = [
        ("q1", "Front-load in Q1", 0.0005),
        ("q2", "Front-half in Q2", 0.0015),
        ("q4", "Back-load in Q4", 0.0050),
    ]

    out = []
    for code, label, penalty_rate in options:
        out.append(
            {
                "strategy_id": f"timing_{code}",
                "label": label,
                "distribution_ratio": target_ratio,
                "distribution_amount": amount,
                "annual_tax": _round2(base_tax),
                "annual_financing_cost": 0.0,
                "annual_penalty": _round2(amount * penalty_rate),
                "annual_after_tax_cash": _as_float(inputs.get("annual_savings"), 0.0),
                "components": {"timing_penalty_rate": penalty_rate},
            }
        )
    return out


def _evaluate_trust_distribution_character_mix(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    trust_type = str(inputs.get("trust_type", "complex"))

    t_ord = _as_float(inputs.get("trust_income_ordinary"))
    t_qdiv = _as_float(inputs.get("trust_income_qualified_dividends"))
    t_ltcg = _as_float(inputs.get("trust_income_long_term_capital_gains"))
    total = t_ord + t_qdiv + t_ltcg
    distribution_ratio = max(0.0, min(1.0, _as_float(inputs.get("target_distribution_ratio"), 0.6)))
    distribution_amount = total * distribution_ratio

    mixes = [
        ("pro_rata", "Pro-rata character distribution", ("ordinary", "qualified_dividends", "long_term_capital_gains"), False),
        ("ordinary_first", "Distribute ordinary income first", ("ordinary", "qualified_dividends", "long_term_capital_gains"), True),
        ("gains_first", "Distribute gains/dividends first", ("long_term_capital_gains", "qualified_dividends", "ordinary"), True),
    ]

    out = []
    for sid, label, order, explicit_order in mixes:
        if explicit_order:
            distributed = _allocate_distribution(distribution_amount, t_ord, t_qdiv, t_ltcg, order)
        else:
            distributed = {
                "ordinary": t_ord * distribution_ratio,
                "qualified_dividends": t_qdiv * distribution_ratio,
                "long_term_capital_gains": t_ltcg * distribution_ratio,
            }

        trust = _estimate_trust_tax(
            t_ord,
            t_qdiv,
            t_ltcg,
            sum(distributed.values()) / total if total > 0 else 0.0,
            trust_type,
        )

        personal = dict(personal_base)
        personal["passive_income"] = personal["passive_income"] + distributed["ordinary"]
        personal["qualified_dividends"] = personal["qualified_dividends"] + distributed["qualified_dividends"]
        personal["capital_gains_long"] = personal["capital_gains_long"] + distributed["long_term_capital_gains"]
        personal_out = _run_personal_projection(personal, state, int(assumptions.get("tax_year", TAX_YEAR)))

        out.append(
            {
                "strategy_id": sid,
                "label": label,
                "distribution_amount": _round2(sum(distributed.values())),
                "annual_tax": _round2(personal_out["total_tax_liability"] + trust["total_trust_tax"]),
                "annual_financing_cost": 0.0,
                "annual_penalty": 0.0,
                "annual_after_tax_cash": _as_float(inputs.get("annual_savings"), 0.0),
                "components": {
                    "distributed_character": {k: _round2(v) for k, v in distributed.items()},
                    "personal_tax": personal_out,
                    "trust_tax": trust,
                },
            }
        )

    return out


def _evaluate_liquidity_heloc_vs_roth(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    personal_out = _run_personal_projection(personal_base, state, int(assumptions.get("tax_year", TAX_YEAR)))

    liquidity_need = max(0.0, _as_float(inputs.get("liquidity_need"), 100_000.0))
    heloc_rate = max(0.0, _as_float(inputs.get("heloc_rate"), 0.08))
    heloc_fee = max(0.0, _as_float(inputs.get("heloc_origination_cost"), 500.0))

    age = _as_float(inputs.get("age"), personal_base.get("age", 45))
    roth_basis_available = max(0.0, _as_float(inputs.get("roth_basis_available"), 0.0))
    filing_status = personal_base["filing_status"]
    ord_rate = _estimate_marginal_ordinary_rate(personal_out["adjusted_gross_income"], filing_status)

    def roth_cost(draw: float) -> tuple[float, float]:
        taxable = max(0.0, draw - roth_basis_available)
        income_tax = taxable * ord_rate
        penalty = taxable * 0.10 if age < 59.5 else 0.0
        return income_tax, penalty

    plans = [
        ("heloc_only", "HELOC only", liquidity_need, 0.0),
        ("roth_only", "Roth distribution only", 0.0, liquidity_need),
        ("mixed_50_50", "50/50 HELOC + Roth", liquidity_need * 0.5, liquidity_need * 0.5),
    ]

    out = []
    for sid, label, heloc_draw, roth_draw in plans:
        roth_tax, roth_penalty = roth_cost(roth_draw)
        annual_financing = heloc_draw * heloc_rate
        one_time_financing = heloc_fee if heloc_draw > 0 else 0.0
        annual_tax = personal_out["total_tax_liability"] + roth_tax

        out.append(
            {
                "strategy_id": sid,
                "label": label,
                "annual_tax": _round2(annual_tax),
                "annual_financing_cost": _round2(annual_financing),
                "annual_penalty": _round2(roth_penalty),
                "annual_after_tax_cash": 0.0,
                "one_time_financing_cost": _round2(one_time_financing),
                "components": {
                    "heloc_draw": _round2(heloc_draw),
                    "roth_draw": _round2(roth_draw),
                    "roth_income_tax": _round2(roth_tax),
                    "roth_penalty": _round2(roth_penalty),
                    "heloc_rate": heloc_rate,
                },
            }
        )
    return out


def _evaluate_roth_conversion_ladder(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    personal_out = _run_personal_projection(personal_base, state, int(assumptions.get("tax_year", TAX_YEAR)))
    filing_status = personal_base["filing_status"]

    baseline_agi = personal_out["adjusted_gross_income"]
    marginal_rate = _estimate_marginal_ordinary_rate(baseline_agi, filing_status)
    future_rate = _as_float(inputs.get("future_ordinary_rate"), min(0.42, marginal_rate + 0.05))

    conversions = inputs.get("conversion_amounts") or [0.0, 50_000.0, 100_000.0]
    out = []
    for amount in conversions:
        conv = max(0.0, _as_float(amount))
        current_tax = conv * marginal_rate
        annual_future_benefit = conv * max(0.0, future_rate - marginal_rate) / max(1, assumptions["horizon_years"])
        out.append(
            {
                "strategy_id": f"conversion_{int(conv)}",
                "label": f"Convert ${int(conv):,}/year",
                "annual_tax": _round2(personal_out["total_tax_liability"] + current_tax),
                "annual_financing_cost": 0.0,
                "annual_penalty": 0.0,
                "annual_after_tax_cash": _round2(annual_future_benefit),
                "components": {
                    "conversion_amount": _round2(conv),
                    "marginal_rate": marginal_rate,
                    "future_rate_assumed": future_rate,
                },
            }
        )
    return out


def _evaluate_taxable_sale_vs_borrowing(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    personal_out = _run_personal_projection(personal_base, state, int(assumptions.get("tax_year", TAX_YEAR)))

    need = max(0.0, _as_float(inputs.get("liquidity_need"), 100_000.0))
    gain_ratio = max(0.0, min(1.0, _as_float(inputs.get("taxable_asset_gain_ratio"), 0.45)))
    cap_rate = _capital_gains_rate(personal_out["adjusted_gross_income"], personal_base["filing_status"])
    heloc_rate = max(0.0, _as_float(inputs.get("heloc_rate"), 0.08))

    plans = [
        ("sell_assets", "Sell taxable assets", need, 0.0),
        ("borrow_heloc", "Borrow via HELOC", 0.0, need),
        ("mixed_50_50", "50/50 sale + HELOC", need * 0.5, need * 0.5),
    ]

    out = []
    for sid, label, sale_amt, debt_amt in plans:
        sale_tax = sale_amt * gain_ratio * cap_rate
        financing = debt_amt * heloc_rate
        out.append(
            {
                "strategy_id": sid,
                "label": label,
                "annual_tax": _round2(personal_out["total_tax_liability"] + sale_tax),
                "annual_financing_cost": _round2(financing),
                "annual_penalty": 0.0,
                "annual_after_tax_cash": 0.0,
                "components": {
                    "sale_amount": _round2(sale_amt),
                    "borrow_amount": _round2(debt_amt),
                    "sale_tax": _round2(sale_tax),
                    "cap_gain_rate": cap_rate,
                },
            }
        )
    return out


def _evaluate_capital_gain_timing(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    personal_out = _run_personal_projection(personal_base, state, int(assumptions.get("tax_year", TAX_YEAR)))

    gain_amount = max(0.0, _as_float(inputs.get("gain_amount"), 120_000.0))
    cap_rate = _capital_gains_rate(personal_out["adjusted_gross_income"], personal_base["filing_status"])

    one_time_tax_now = gain_amount * cap_rate
    spread_tax = (gain_amount / 3.0) * cap_rate
    deferred_tax = gain_amount * cap_rate * 1.05

    return [
        {
            "strategy_id": "realize_now",
            "label": "Realize all gains now",
            "annual_tax": _round2(personal_out["total_tax_liability"]),
            "one_time_tax": _round2(one_time_tax_now),
            "annual_financing_cost": 0.0,
            "annual_penalty": 0.0,
            "annual_after_tax_cash": 0.0,
            "components": {"gain_amount": _round2(gain_amount), "capital_gains_rate": cap_rate},
        },
        {
            "strategy_id": "spread_3_years",
            "label": "Spread realization over 3 years",
            "annual_tax": _round2(personal_out["total_tax_liability"] + spread_tax),
            "annual_financing_cost": 0.0,
            "annual_penalty": 0.0,
            "annual_after_tax_cash": 0.0,
            "components": {"gain_amount": _round2(gain_amount), "capital_gains_rate": cap_rate},
        },
        {
            "strategy_id": "defer_realization",
            "label": "Defer realization",
            "annual_tax": _round2(personal_out["total_tax_liability"]),
            "one_time_tax": _round2(deferred_tax),
            "annual_financing_cost": 0.0,
            "annual_penalty": 0.0,
            "annual_after_tax_cash": _round2(gain_amount * 0.01),
            "components": {"gain_amount": _round2(gain_amount), "capital_gains_rate": cap_rate},
        },
    ]


def _evaluate_estimated_tax_method(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    annual_tax = max(0.0, _as_float(inputs.get("annual_total_tax"), 150_000.0))
    withholding = max(0.0, _as_float(inputs.get("annual_withholding"), annual_tax * 0.25))
    volatility = max(0.0, _as_float(inputs.get("income_volatility_factor"), 1.0))

    underpaid = max(0.0, annual_tax - withholding)

    return [
        {
            "strategy_id": "equal_installments",
            "label": "Equal quarterly installments",
            "annual_tax": _round2(annual_tax),
            "annual_financing_cost": 0.0,
            "annual_penalty": _round2(underpaid * 0.012 * volatility),
            "annual_after_tax_cash": 0.0,
            "components": {"method": "equal", "underpaid_base": _round2(underpaid)},
        },
        {
            "strategy_id": "annualized_installments",
            "label": "Annualized income installment method",
            "annual_tax": _round2(annual_tax),
            "annual_financing_cost": 0.0,
            "annual_penalty": _round2(underpaid * 0.004 * volatility),
            "annual_after_tax_cash": 0.0,
            "components": {"method": "annualized", "underpaid_base": _round2(underpaid)},
        },
    ]


def _evaluate_withholding_vs_quarterly(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    annual_tax = max(0.0, _as_float(inputs.get("annual_total_tax"), 150_000.0))

    scenarios = [
        ("high_withholding", "Bias to wage withholding", annual_tax * 0.85, annual_tax * 0.15, annual_tax * 0.0005),
        ("high_quarterly", "Bias to quarterly estimates", annual_tax * 0.20, annual_tax * 0.80, annual_tax * 0.0035),
        ("hybrid", "Balanced withholding + quarterly", annual_tax * 0.50, annual_tax * 0.50, annual_tax * 0.0015),
    ]

    out = []
    for sid, label, withholding, estimates, penalty in scenarios:
        idle_cash_drag = max(0.0, withholding - annual_tax * 0.5) * 0.01
        out.append(
            {
                "strategy_id": sid,
                "label": label,
                "annual_tax": _round2(annual_tax),
                "annual_financing_cost": _round2(idle_cash_drag),
                "annual_penalty": _round2(penalty),
                "annual_after_tax_cash": 0.0,
                "components": {
                    "withholding": _round2(withholding),
                    "estimated_payments": _round2(estimates),
                },
            }
        )
    return out


def _evaluate_ftc_strategy(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    personal_out = _run_personal_projection(personal_base, state, int(assumptions.get("tax_year", TAX_YEAR)))

    us_tax_before_credit = max(0.0, _as_float(inputs.get("us_tax_before_credits"), personal_out["federal_income_tax"]))
    current_ftc = max(0.0, _as_float(inputs.get("current_year_foreign_tax_credit"), 2_000.0))
    carry_gen = max(0.0, _as_float(inputs.get("carryover_general"), 0.0))
    carry_passive = max(0.0, _as_float(inputs.get("carryover_passive"), 0.0))

    plans = [
        ("use_current_only", "Use current-year credits only", current_ftc, carry_gen + carry_passive, 0.0),
        ("preserve_carryovers", "Preserve carryovers for future years", current_ftc * 0.8, carry_gen + carry_passive * 1.02, 150.0),
        ("accelerate_utilization", "Accelerate carryover utilization", min(us_tax_before_credit, current_ftc + 0.4 * (carry_gen + carry_passive)), max(0.0, 0.6 * (carry_gen + carry_passive)), -50.0),
    ]

    out = []
    for sid, label, credit_used, carryover_end, planning_cost in plans:
        federal_after_credit = max(0.0, personal_out["federal_income_tax"] - credit_used)
        annual_tax = federal_after_credit + personal_out["self_employment_tax"] + personal_out["state_income_tax"]
        out.append(
            {
                "strategy_id": sid,
                "label": label,
                "annual_tax": _round2(annual_tax),
                "annual_financing_cost": _round2(planning_cost),
                "annual_penalty": 0.0,
                "annual_after_tax_cash": 0.0,
                "components": {
                    "credit_used": _round2(credit_used),
                    "carryover_end": _round2(carryover_end),
                },
            }
        )
    return out


BUSINESS_STRUCTURES = {"sole_prop", "s_corp_owner", "partnership_owner"}
RETIREMENT_PLANS = {"solo_401k", "sep_ira", "defined_benefit", "none"}
QBI_PHASEOUT_STATUS = {"below", "phaseout", "above"}


def _validate_owner_comp_mix(mix: dict[str, Any], entity_income: float, mix_id: str = "mix") -> dict[str, Any]:
    w2_comp = max(0.0, _as_float(mix.get("w2_comp")))
    distribution = max(0.0, _as_float(mix.get("distribution")))
    guaranteed = max(0.0, _as_float(mix.get("guaranteed_payments")))
    total = w2_comp + distribution + guaranteed
    if total > entity_income + 1e-6:
        raise ValueError(
            f"owner_comp_mix '{mix_id}' exceeds entity_income: {total:.2f} > {entity_income:.2f}"
        )
    return {
        "id": str(mix.get("id") or mix_id),
        "w2_comp": w2_comp,
        "distribution": distribution,
        "guaranteed_payments": guaranteed,
    }


def _validate_retirement_election(election: dict[str, Any], default_id: str = "retirement") -> dict[str, Any]:
    plan = str(election.get("plan") or "").strip().lower()
    if plan not in RETIREMENT_PLANS:
        allowed = ", ".join(sorted(RETIREMENT_PLANS))
        raise ValueError(f"retirement_election.plan must be one of: {allowed}")
    contribution = max(0.0, _as_float(election.get("contribution")))
    return {
        "id": str(election.get("id") or default_id),
        "plan": plan,
        "contribution": contribution,
    }


def _default_retirement_grid(entity_income: float) -> list[dict[str, Any]]:
    return [
        {"id": "none", "plan": "none", "contribution": 0.0},
        {"id": "sep_ira", "plan": "sep_ira", "contribution": min(69_000.0, entity_income * 0.20)},
        {
            "id": "solo_401k",
            "plan": "solo_401k",
            "contribution": min(69_000.0, 23_000.0 + entity_income * 0.15),
        },
        {
            "id": "defined_benefit",
            "plan": "defined_benefit",
            "contribution": min(200_000.0, entity_income * 0.35),
        },
    ]


def _default_owner_comp_mix_grid(
    business_structure: str,
    entity_income: float,
    base_mix: dict[str, Any],
) -> list[dict[str, Any]]:
    base = dict(base_mix)
    candidates: list[dict[str, Any]] = [base]

    if business_structure == "s_corp_owner":
        candidates.extend(
            [
                {"id": "w2_70_dist_30", "w2_comp": entity_income * 0.70, "distribution": entity_income * 0.30, "guaranteed_payments": 0.0},
                {"id": "w2_50_dist_50", "w2_comp": entity_income * 0.50, "distribution": entity_income * 0.50, "guaranteed_payments": 0.0},
                {"id": "w2_30_dist_70", "w2_comp": entity_income * 0.30, "distribution": entity_income * 0.70, "guaranteed_payments": 0.0},
            ]
        )
    elif business_structure == "partnership_owner":
        candidates.extend(
            [
                {"id": "gp_70_dist_30", "w2_comp": 0.0, "distribution": entity_income * 0.30, "guaranteed_payments": entity_income * 0.70},
                {"id": "gp_50_dist_50", "w2_comp": 0.0, "distribution": entity_income * 0.50, "guaranteed_payments": entity_income * 0.50},
                {"id": "gp_30_dist_70", "w2_comp": 0.0, "distribution": entity_income * 0.70, "guaranteed_payments": entity_income * 0.30},
            ]
        )
    else:
        candidates.extend(
            [
                {"id": "sole_100_dist", "w2_comp": 0.0, "distribution": entity_income, "guaranteed_payments": 0.0},
                {"id": "sole_80_dist_20_gp", "w2_comp": 0.0, "distribution": entity_income * 0.80, "guaranteed_payments": entity_income * 0.20},
            ]
        )

    unique: dict[tuple[float, float, float], dict[str, Any]] = {}
    for idx, c in enumerate(candidates, start=1):
        normalized = _validate_owner_comp_mix(c, entity_income, mix_id=str(c.get("id") or f"mix_{idx}"))
        key = (
            _round2(normalized["w2_comp"]),
            _round2(normalized["distribution"]),
            _round2(normalized["guaranteed_payments"]),
        )
        if key not in unique:
            unique[key] = normalized
    return list(unique.values())


def _normalize_business_owner_inputs(inputs: dict[str, Any], state: str) -> dict[str, Any]:
    required = [
        "business_structure",
        "owner_comp_mix",
        "retirement_election",
        "entity_income",
        "payroll_taxes",
        "qbi_inputs",
        "state_inputs",
    ]
    missing = [k for k in required if k not in inputs]
    if missing:
        raise ValueError(f"Missing required scenario #11 inputs: {', '.join(missing)}")

    business_structure = str(inputs.get("business_structure") or "").strip().lower()
    if business_structure not in BUSINESS_STRUCTURES:
        allowed = ", ".join(sorted(BUSINESS_STRUCTURES))
        raise ValueError(f"business_structure must be one of: {allowed}")

    entity_income = max(0.0, _as_float(inputs.get("entity_income")))
    if entity_income <= 0:
        raise ValueError("entity_income must be > 0")

    state_inputs = dict(inputs.get("state_inputs") or {})
    state_name = str(state_inputs.get("state") or state).upper()
    if state_name != state:
        raise ValueError(f"state_inputs.state '{state_name}' must match scenario state '{state}'")
    state_effective_rate = max(0.0, _as_float(state_inputs.get("effective_rate"), MA_EFFECTIVE_RATE))

    payroll_taxes = dict(inputs.get("payroll_taxes") or {})
    for key in ("fica_rate", "medicare_addl_rate", "se_income_factor"):
        if key not in payroll_taxes:
            raise ValueError(f"payroll_taxes.{key} is required")
    payroll = {
        "fica_rate": max(0.0, _as_float(payroll_taxes.get("fica_rate"))),
        "medicare_addl_rate": max(0.0, _as_float(payroll_taxes.get("medicare_addl_rate"))),
        "se_income_factor": max(0.0, _as_float(payroll_taxes.get("se_income_factor"), 0.9235)),
    }

    qbi_inputs = dict(inputs.get("qbi_inputs") or {})
    for key in ("eligible_income", "w2_wages", "ubia", "phaseout_status"):
        if key not in qbi_inputs:
            raise ValueError(f"qbi_inputs.{key} is required")
    phaseout_status = str(qbi_inputs.get("phaseout_status") or "").strip().lower()
    if phaseout_status not in QBI_PHASEOUT_STATUS:
        allowed = ", ".join(sorted(QBI_PHASEOUT_STATUS))
        raise ValueError(f"qbi_inputs.phaseout_status must be one of: {allowed}")
    qbi = {
        "eligible_income": max(0.0, _as_float(qbi_inputs.get("eligible_income"))),
        "w2_wages": max(0.0, _as_float(qbi_inputs.get("w2_wages"))),
        "ubia": max(0.0, _as_float(qbi_inputs.get("ubia"))),
        "phaseout_status": phaseout_status,
    }

    base_mix = _validate_owner_comp_mix(dict(inputs.get("owner_comp_mix") or {}), entity_income, "owner_comp_mix")
    base_retirement = _validate_retirement_election(dict(inputs.get("retirement_election") or {}), "retirement_election")

    sensitivity = dict(inputs.get("sensitivity") or {})
    mix_grid_raw = sensitivity.get("owner_comp_mix_grid")
    if mix_grid_raw is None:
        mix_grid = _default_owner_comp_mix_grid(business_structure, entity_income, base_mix)
    else:
        if not isinstance(mix_grid_raw, list) or not mix_grid_raw:
            raise ValueError("sensitivity.owner_comp_mix_grid must be a non-empty list when provided")
        mix_grid = [
            _validate_owner_comp_mix(dict(m), entity_income, f"owner_comp_mix_grid[{idx}]")
            for idx, m in enumerate(mix_grid_raw)
        ]
        has_base = any(
            _round2(m.get("w2_comp", 0.0)) == _round2(base_mix["w2_comp"])
            and _round2(m.get("distribution", 0.0)) == _round2(base_mix["distribution"])
            and _round2(m.get("guaranteed_payments", 0.0)) == _round2(base_mix["guaranteed_payments"])
            for m in mix_grid
        )
        if not has_base:
            mix_grid.insert(0, base_mix)

    retirement_grid_raw = sensitivity.get("retirement_grid")
    if retirement_grid_raw is None:
        retirement_grid = _default_retirement_grid(entity_income)
    else:
        if not isinstance(retirement_grid_raw, list) or not retirement_grid_raw:
            raise ValueError("sensitivity.retirement_grid must be a non-empty list when provided")
        retirement_grid = [
            _validate_retirement_election(dict(e), f"retirement_grid[{idx}]")
            for idx, e in enumerate(retirement_grid_raw)
        ]
        if all(e.get("plan") != base_retirement["plan"] or _round2(e.get("contribution", 0.0)) != _round2(base_retirement["contribution"]) for e in retirement_grid):
            retirement_grid.insert(0, base_retirement)

    return {
        "business_structure": business_structure,
        "entity_income": entity_income,
        "owner_comp_mix_grid": mix_grid,
        "retirement_grid": retirement_grid,
        "payroll_taxes": payroll,
        "qbi_inputs": qbi,
        "state_inputs": {"state": state_name, "effective_rate": state_effective_rate},
    }


def _evaluate_business_owner_comp_and_retirement(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    filing_status = personal_base["filing_status"]
    norm = _normalize_business_owner_inputs(inputs, state)

    phase_factor = {
        "below": 1.0,
        "phaseout": 0.5,
        "above": 0.0,
    }[norm["qbi_inputs"]["phaseout_status"]]

    alternatives: list[dict[str, Any]] = []
    for mix in norm["owner_comp_mix_grid"]:
        for election in norm["retirement_grid"]:
            p = dict(personal_base)
            w2_comp = _as_float(mix.get("w2_comp"))
            distribution = _as_float(mix.get("distribution"))
            guaranteed = _as_float(mix.get("guaranteed_payments"))
            contribution = _as_float(election.get("contribution"))

            p["w2_income"] += w2_comp
            payroll_wage_base = w2_comp

            if norm["business_structure"] == "sole_prop":
                p["self_employment_income"] += distribution + guaranteed
            elif norm["business_structure"] == "partnership_owner":
                se_component = guaranteed + (distribution * norm["payroll_taxes"]["se_income_factor"])
                p["self_employment_income"] += se_component
                payroll_wage_base += max(0.0, guaranteed)
            else:
                # s-corp owner
                p["passive_income"] += distribution
                p["w2_income"] += guaranteed
                payroll_wage_base += guaranteed

            p["retirement_contributions"] += contribution
            personal_out = _run_personal_projection(p, state, int(assumptions.get("tax_year", TAX_YEAR)))

            payroll_rate = norm["payroll_taxes"]["fica_rate"] + norm["payroll_taxes"]["medicare_addl_rate"]
            payroll_tax = payroll_wage_base * payroll_rate
            se_tax = _as_float(personal_out.get("self_employment_tax"))

            adjusted_agi = _as_float(personal_out.get("adjusted_gross_income"))
            marginal = _estimate_marginal_ordinary_rate(adjusted_agi, filing_status)

            qbi_eligible = max(
                0.0,
                _as_float(norm["qbi_inputs"].get("eligible_income"))
                - w2_comp
                - guaranteed
                - contribution,
            )
            qbi_deduction = qbi_eligible * 0.20 * phase_factor
            qbi_tax_shield = qbi_deduction * marginal

            federal_tax = _as_float(personal_out.get("federal_income_tax"))
            modeled_state_tax = adjusted_agi * _as_float(norm["state_inputs"].get("effective_rate"), MA_EFFECTIVE_RATE)
            state_tax = max(_as_float(personal_out.get("state_income_tax")), modeled_state_tax)
            total_tax = max(0.0, federal_tax + state_tax + se_tax + payroll_tax - qbi_tax_shield)

            tax_deferral_value = contribution * marginal
            strategy_id = f"{mix.get('id','mix')}_{election.get('plan','retirement')}"
            label = f"{mix.get('id','mix')} + {election.get('plan','retirement')} election"

            tax_totals = {
                "federal_income_tax": _round2(federal_tax),
                "state_income_tax": _round2(state_tax),
                "self_employment_tax": _round2(se_tax),
                "payroll_tax": _round2(payroll_tax),
                "total_tax": _round2(total_tax),
            }
            qbi_effects = {
                "qbi_deduction": _round2(qbi_deduction),
                "qbi_tax_shield": _round2(qbi_tax_shield),
                "phaseout_status": norm["qbi_inputs"]["phaseout_status"],
            }
            retirement_effects = {
                "plan": election.get("plan"),
                "contribution": _round2(contribution),
                "tax_deferral_value": _round2(tax_deferral_value),
            }
            cashflow_effects = {
                "annual_after_tax_cash": _round2(contribution),
                "one_time_cashflow": 0.0,
            }
            estimated_payment_implications = {
                "annual_estimated_tax": _round2(total_tax),
                "quarterly_installment_estimate": math.ceil(max(0.0, total_tax) / 4.0),
            }

            alternatives.append(
                {
                    "strategy_id": strategy_id,
                    "label": label,
                    "annual_tax": _round2(total_tax),
                    "annual_financing_cost": 0.0,
                    "annual_penalty": 0.0,
                    "annual_after_tax_cash": _round2(contribution),
                    "one_time_cashflow": 0.0,
                    "tax_totals": tax_totals,
                    "qbi_effects": qbi_effects,
                    "retirement_effects": retirement_effects,
                    "cashflow_effects": cashflow_effects,
                    "estimated_payment_implications": estimated_payment_implications,
                    "components": {
                        "business_structure": norm["business_structure"],
                        "w2_compensation": _round2(w2_comp),
                        "distribution_income": _round2(distribution),
                        "guaranteed_payments": _round2(guaranteed),
                        "retirement_contribution": _round2(contribution),
                        "qbi_deduction": _round2(qbi_deduction),
                        "qbi_tax_shield": _round2(qbi_tax_shield),
                        "payroll_tax_drag": _round2(payroll_tax),
                        "personal_tax": personal_out,
                    },
                }
            )

    return alternatives



def _evaluate_schedule_c_timing(
    inputs: dict[str, Any], assumptions: dict[str, Any], state: str
) -> list[dict[str, Any]]:
    personal_base = _base_personal_inputs(inputs)
    personal_out = _run_personal_projection(personal_base, state, int(assumptions.get("tax_year", TAX_YEAR)))

    discretionary = max(0.0, _as_float(inputs.get("discretionary_schedule_c_expenses"), 30_000.0))
    rate = _estimate_marginal_ordinary_rate(personal_out["adjusted_gross_income"], personal_base["filing_status"])

    accel_benefit = discretionary * rate

    return [
        {
            "strategy_id": "accelerate_expenses",
            "label": "Accelerate deductible Schedule C expenses",
            "annual_tax": _round2(max(0.0, personal_out["total_tax_liability"] - accel_benefit * 0.35)),
            "annual_financing_cost": 0.0,
            "annual_penalty": 0.0,
            "annual_after_tax_cash": _round2(accel_benefit * 0.10),
            "one_time_cashflow": _round2(accel_benefit * 0.20),
            "components": {"discretionary_expenses": _round2(discretionary), "marginal_rate": rate},
        },
        {
            "strategy_id": "neutral_timing",
            "label": "Keep expense timing neutral",
            "annual_tax": _round2(personal_out["total_tax_liability"]),
            "annual_financing_cost": 0.0,
            "annual_penalty": 0.0,
            "annual_after_tax_cash": 0.0,
            "components": {"discretionary_expenses": _round2(discretionary), "marginal_rate": rate},
        },
        {
            "strategy_id": "defer_expenses",
            "label": "Defer discretionary expenses",
            "annual_tax": _round2(personal_out["total_tax_liability"] + accel_benefit * 0.20),
            "annual_financing_cost": 0.0,
            "annual_penalty": 0.0,
            "annual_after_tax_cash": _round2(discretionary * 0.05),
            "components": {"discretionary_expenses": _round2(discretionary), "marginal_rate": rate},
        },
    ]


def _scenario_alternatives(
    scenario_id: str,
    inputs: dict[str, Any],
    assumptions: dict[str, Any],
    state: str,
) -> list[dict[str, Any]]:
    if scenario_id == "trust_distribute_vs_retain_income":
        return _evaluate_trust_distribute_vs_retain(inputs, assumptions, state)
    if scenario_id == "trust_distribution_timing_within_tax_year":
        return _evaluate_trust_distribution_timing(inputs, assumptions, state)
    if scenario_id == "trust_distribution_character_mix":
        return _evaluate_trust_distribution_character_mix(inputs, assumptions, state)
    if scenario_id == "liquidity_heloc_vs_roth_distribution_vs_mixed":
        return _evaluate_liquidity_heloc_vs_roth(inputs, assumptions, state)
    if scenario_id == "roth_conversion_ladder_vs_no_conversion":
        return _evaluate_roth_conversion_ladder(inputs, assumptions, state)
    if scenario_id == "taxable_asset_sale_vs_borrowing_for_liquidity":
        return _evaluate_taxable_sale_vs_borrowing(inputs, assumptions, state)
    if scenario_id == "capital_gain_realization_timing_personal_plus_trust":
        return _evaluate_capital_gain_timing(inputs, assumptions, state)
    if scenario_id == "estimated_tax_method_equal_vs_annualized_installments":
        return _evaluate_estimated_tax_method(inputs, assumptions, state)
    if scenario_id == "withholding_vs_quarterly_payments_for_penalty_control":
        return _evaluate_withholding_vs_quarterly(inputs, assumptions, state)
    if scenario_id == "foreign_tax_credit_utilization_and_carryover_strategy":
        return _evaluate_ftc_strategy(inputs, assumptions, state)
    if scenario_id == "business_owner_compensation_and_retirement_election_strategy":
        return _evaluate_business_owner_comp_and_retirement(inputs, assumptions, state)
    if scenario_id == "schedule_c_expense_timing_accelerate_vs_defer":
        return _evaluate_schedule_c_timing(inputs, assumptions, state)

    raise ValueError(f"Unsupported scenario_id: {scenario_id}")


def _rank_key(objective: str, alt: dict[str, Any]) -> float:
    if objective == "max_end_net_worth":
        return -_as_float(alt.get("ending_net_worth"))
    if objective == "min_total_economic_cost":
        return _as_float(alt.get("total_economic_cost"))
    # min_current_year_cash_tax
    return _as_float(alt.get("annual_tax")) + _as_float(alt.get("annual_penalty"))


def _build_installment_plan(annual_total_tax: float, horizon_years: int, tax_year: int) -> dict[str, Any]:
    annual_total_tax = max(0.0, annual_total_tax)
    installment = math.ceil(annual_total_tax / 4.0)
    due_dates = [
        f"{tax_year}-04-15",
        f"{tax_year}-06-15",
        f"{tax_year}-09-15",
        f"{tax_year + 1}-01-15",
    ]
    return {
        "tax_year": tax_year,
        "annual_total_tax": _round2(annual_total_tax),
        "installments": [
            {"quarter": f"Q{i + 1}", "due_date": due_dates[i], "amount": installment}
            for i in range(4)
        ],
        "planning_horizon_years": horizon_years,
    }


def _build_sensitivity_table(scenario_id: str, alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if scenario_id != "business_owner_compensation_and_retirement_election_strategy":
        return []
    rows = []
    for alt in alternatives:
        rows.append(
            {
                "strategy_id": alt.get("strategy_id"),
                "label": alt.get("label"),
                "annual_tax": _round2(_as_float(alt.get("annual_tax"))),
                "ending_net_worth": _round2(_as_float(alt.get("ending_net_worth"))),
                "total_economic_cost": _round2(_as_float(alt.get("total_economic_cost"))),
                "w2_compensation": _round2(_as_float(alt.get("components", {}).get("w2_compensation"))),
                "distribution_income": _round2(_as_float(alt.get("components", {}).get("distribution_income"))),
                "guaranteed_payments": _round2(_as_float(alt.get("components", {}).get("guaranteed_payments"))),
                "retirement_plan": alt.get("retirement_effects", {}).get("plan"),
                "retirement_contribution": _round2(_as_float(alt.get("retirement_effects", {}).get("contribution"))),
                "qbi_deduction": _round2(_as_float(alt.get("qbi_effects", {}).get("qbi_deduction"))),
            }
        )
    return rows


def _attach_deltas(alternatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not alternatives:
        return alternatives
    baseline = alternatives[0]
    base_tax = _as_float(baseline.get("annual_tax"))
    base_cash = _as_float(baseline.get("annual_after_tax_cash"))
    base_nw = _as_float(baseline.get("ending_net_worth"))
    for alt in alternatives:
        alt["deltas"] = {
            "annual_tax_delta_vs_recommended": _round2(_as_float(alt.get("annual_tax")) - base_tax),
            "annual_after_tax_cash_delta_vs_recommended": _round2(
                _as_float(alt.get("annual_after_tax_cash")) - base_cash
            ),
            "ending_net_worth_delta_vs_recommended": _round2(
                _as_float(alt.get("ending_net_worth")) - base_nw
            ),
        }
    return alternatives


def _evaluate_scenario_internal(
    scenario_id: str,
    inputs: dict[str, Any],
    assumptions: dict[str, Any],
) -> dict[str, Any]:
    if scenario_id not in SCENARIO_DEFINITIONS:
        raise ValueError(f"Unsupported scenario_id: {scenario_id}")

    objective = assumptions["objective"]
    horizon = assumptions["horizon_years"]
    state = _active_state_from_inputs(inputs, assumptions)
    tax_year = int(inputs.get("tax_year") or assumptions.get("tax_year") or TAX_YEAR)
    assumptions["tax_year"] = tax_year

    alternatives = _scenario_alternatives(scenario_id, inputs, assumptions, state)
    ranked = []
    for alt in alternatives:
        simulation = _simulate_net_worth(
            annual_tax=_as_float(alt.get("annual_tax")),
            annual_financing_cost=_as_float(alt.get("annual_financing_cost")),
            annual_penalty=_as_float(alt.get("annual_penalty")),
            annual_after_tax_cash=_as_float(alt.get("annual_after_tax_cash")),
            assumptions=assumptions,
            horizon_years=horizon,
            one_time_tax=_as_float(alt.get("one_time_tax")),
            one_time_financing_cost=_as_float(alt.get("one_time_financing_cost")),
            one_time_penalty=_as_float(alt.get("one_time_penalty")),
            one_time_cashflow=_as_float(alt.get("one_time_cashflow")),
        )

        enriched = {
            **alt,
            "ending_net_worth": simulation["ending_net_worth"],
            "total_economic_cost": simulation["total_economic_cost"],
            "trajectory": simulation["trajectory"],
        }
        ranked.append(enriched)

    ranked.sort(key=lambda x: (_rank_key(objective, x), str(x.get("strategy_id", ""))))
    for idx, alt in enumerate(ranked, start=1):
        alt["rank"] = idx

    ranked = _attach_deltas(ranked)
    recommended = ranked[0]
    run_id = str(uuid.uuid4())

    plan = _build_installment_plan(
        annual_total_tax=_as_float(recommended.get("annual_tax")) + _as_float(recommended.get("annual_penalty")),
        horizon_years=horizon,
        tax_year=tax_year,
    )
    plan_id = str(uuid.uuid4())
    plan_record = {
        **plan,
        "plan_id": plan_id,
        "scenario_id": scenario_id,
        "run_id": run_id,
        "created_at": _now_iso(),
    }
    PLAN_STORE[plan_id] = plan_record
    _persist_plan(plan_record)

    result = {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_name": SCENARIO_DEFINITIONS[scenario_id]["title"],
        "objective": objective,
        "horizon_years": horizon,
        "state": state,
        "tax_year": tax_year,
        "inputs": inputs,
        "assumptions": assumptions,
        "recommended": recommended,
        "alternatives": ranked,
        "estimated_payments_plan_id": plan_id,
        "provenance": {
            "model": "household-tax-mcp-v2",
            "generated_at": _now_iso(),
            "active_state_scope": sorted(ACTIVE_FORWARD_STATES),
            "active_jurisdictions": ["US", state],
        },
    }
    sensitivity_table = _build_sensitivity_table(scenario_id, ranked)
    if sensitivity_table:
        result["sensitivity_table"] = sensitivity_table

    RUN_STORE[run_id] = result
    _persist_run(result, inputs=inputs, assumptions=assumptions)
    return result


@mcp.tool()
def ingest_returns(
    year: int,
    entity_type: str,
    source_path: str,
) -> dict[str, Any]:
    """Ingest return source text/PDF and extract forms, schedules, and complexity flags."""
    normalized_entity = entity_type.strip().lower()
    if normalized_entity not in {"individual", "trust"}:
        raise ValueError("entity_type must be 'individual' or 'trust'")

    text = _extract_text(source_path)
    forms = _detect_forms(text)
    schedules = _detect_schedules(text)
    jurisdictions = _detect_jurisdictions(text)

    manual_flags = sorted(set(forms) & READINESS_COMPLEX_MANUAL_FORMS)

    return_id = str(uuid.uuid4())
    record = {
        "return_id": return_id,
        "year": int(year),
        "entity_type": normalized_entity,
        "source_path": str(Path(source_path).expanduser()),
        "forms_detected": forms,
        "schedules_detected": schedules,
        "jurisdictions_detected": jurisdictions,
        "manual_review_flags": manual_flags,
        "extracted_text_hash": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest(),
        "ingested_at": _now_iso(),
    }
    RETURN_STORE[return_id] = record
    _persist_return(record)

    return {
        **record,
        "summary": {
            "form_count": len(forms),
            "schedule_count": len(schedules),
            "manual_review_required": bool(manual_flags),
        },
    }


@mcp.tool()
def upsert_tax_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Create or update a planning profile used by scenario tools."""
    profile_id = str(profile.get("profile_id") or "default")
    payload = dict(profile)
    payload["profile_id"] = profile_id
    payload["updated_at"] = _now_iso()
    PROFILE_STORE[profile_id] = payload
    _persist_profile(payload)
    return {"status": "ok", "profile_id": profile_id, "profile": payload}


@mcp.tool()
def evaluate_scenario(
    scenario_id: str,
    inputs: dict[str, Any],
    assumptions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a hard-coded scenario and return ranked strategy alternatives."""
    assumptions_payload = _assumptions(assumptions)
    return _evaluate_scenario_internal(scenario_id, dict(inputs), assumptions_payload)


@mcp.tool()
def compare_scenarios(
    requests: list[dict[str, Any]],
    objective: str = DEFAULT_OBJECTIVE,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> dict[str, Any]:
    """Evaluate and compare multiple scenarios under a shared objective and horizon."""
    if not requests:
        raise ValueError("requests cannot be empty")

    base_assumptions = _assumptions(
        {
            "objective": objective,
            "horizon_years": horizon_years,
        }
    )

    scenario_results = []
    for req in requests:
        sid = str(req.get("scenario_id") or "").strip()
        if not sid:
            raise ValueError("Each request must include scenario_id")
        req_inputs = dict(req.get("inputs") or {})
        req_assumptions = dict(base_assumptions)
        req_assumptions.update(dict(req.get("assumptions") or {}))
        req_assumptions = _assumptions(req_assumptions)
        result = _evaluate_scenario_internal(sid, req_inputs, req_assumptions)
        scenario_results.append(
            {
                "scenario_id": sid,
                "scenario_name": result["scenario_name"],
                "run_id": result["run_id"],
                "recommended_strategy": result["recommended"]["strategy_id"],
                "recommended_ending_net_worth": result["recommended"]["ending_net_worth"],
                "recommended_total_economic_cost": result["recommended"]["total_economic_cost"],
                "result": result,
            }
        )

    scenario_results.sort(
        key=lambda x: (
            _rank_key(
                base_assumptions["objective"],
                {
                    "ending_net_worth": x["recommended_ending_net_worth"],
                    "total_economic_cost": x["recommended_total_economic_cost"],
                    "annual_tax": x["result"]["recommended"]["annual_tax"],
                    "annual_penalty": x["result"]["recommended"].get("annual_penalty", 0.0),
                },
            ),
            str(x.get("scenario_id", "")),
        )
    )

    for idx, row in enumerate(scenario_results, start=1):
        row["rank"] = idx

    return {
        "objective": base_assumptions["objective"],
        "horizon_years": base_assumptions["horizon_years"],
        "scenario_count": len(scenario_results),
        "scenarios": scenario_results,
        "best_scenario": scenario_results[0],
        "generated_at": _now_iso(),
    }


@mcp.tool()
def optimize_strategy(
    strategy_group_id: str,
    inputs: dict[str, Any],
    constraints: dict[str, Any] | None = None,
    objective: str = DEFAULT_OBJECTIVE,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
) -> dict[str, Any]:
    """Optimize a multi-scenario strategy group and return the best recommendation."""
    group_id = strategy_group_id.strip().lower()
    if group_id not in STRATEGY_GROUPS:
        allowed = ", ".join(sorted(STRATEGY_GROUPS))
        raise ValueError(f"Unsupported strategy_group_id '{group_id}'. Supported: {allowed}")

    constraint_payload = dict(constraints or {})
    assumptions = _assumptions(
        {
            "objective": objective,
            "horizon_years": horizon_years,
            **constraint_payload,
        }
    )

    scenarios = STRATEGY_GROUPS[group_id]["scenarios"]
    requests = [{"scenario_id": sid, "inputs": dict(inputs)} for sid in scenarios]
    compared = compare_scenarios(
        requests=requests,
        objective=assumptions["objective"],
        horizon_years=assumptions["horizon_years"],
    )

    return {
        "strategy_group_id": group_id,
        "strategy_group_name": STRATEGY_GROUPS[group_id]["title"],
        "objective": assumptions["objective"],
        "horizon_years": assumptions["horizon_years"],
        "best": compared["best_scenario"],
        "scenarios": compared["scenarios"],
        "constraints": constraint_payload,
        "generated_at": _now_iso(),
    }


@mcp.tool()
def generate_estimated_payments_plan(plan_id: str) -> dict[str, Any]:
    """Return estimated payment plan by plan id generated during scenario evaluation."""
    plan = PLAN_STORE.get(plan_id) or _load_plan(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan_id: {plan_id}")
    return plan


@mcp.tool()
def filing_readiness_report(year: int, entity_type: str) -> dict[str, Any]:
    """Generate a readiness report from ingested returns and supported/unsupported forms."""
    normalized_entity = entity_type.strip().lower()
    matches = [
        r
        for r in RETURN_STORE.values()
        if int(r.get("year", 0)) == int(year) and r.get("entity_type") == normalized_entity
    ]

    db_rows = _load_returns(int(year), normalized_entity)
    for row in db_rows:
        if row.get("return_id") not in {m.get("return_id") for m in matches}:
            matches.append(row)

    if not matches:
        raise ValueError(
            "No ingested returns found for requested year/entity_type. "
            "Run ingest_returns first."
        )

    forms = sorted({f for row in matches for f in row.get("forms_detected", [])})
    unsupported = sorted(set(forms) - READINESS_SUPPORTED_FORMS)
    manual = sorted(set(forms) & READINESS_COMPLEX_MANUAL_FORMS)

    ready = not unsupported and not manual

    return {
        "year": int(year),
        "entity_type": normalized_entity,
        "return_count": len(matches),
        "forms_detected": forms,
        "unsupported_forms": unsupported,
        "manual_review_forms": manual,
        "readiness": "ready" if ready else "manual_review_required",
        "ready_to_file_estimate": ready,
        "note": (
            "This report is planning-only. Manual review is required for complex or unsupported forms."
        ),
        "provenance": {
            "generated_at": _now_iso(),
            "supported_form_count": len(READINESS_SUPPORTED_FORMS),
        },
    }


@mcp.tool()
def explain_recommendation(result_id: str) -> dict[str, Any]:
    """Explain why a strategy was recommended for a stored scenario run."""
    run = RUN_STORE.get(result_id) or _load_run(result_id)
    if not run:
        raise ValueError(f"Unknown result_id: {result_id}")

    rec = run["recommended"]
    objective = run["objective"]
    summary = (
        f"Recommended strategy '{rec['strategy_id']}' for scenario '{run['scenario_id']}' "
        f"because it ranks best for objective '{objective}' over {run['horizon_years']} years."
    )
    rationale: dict[str, Any] = {}
    if run.get("scenario_id") == "business_owner_compensation_and_retirement_election_strategy":
        rationale = {
            "business_structure": rec.get("components", {}).get("business_structure"),
            "owner_comp_mix": {
                "w2_compensation": rec.get("components", {}).get("w2_compensation"),
                "distribution_income": rec.get("components", {}).get("distribution_income"),
                "guaranteed_payments": rec.get("components", {}).get("guaranteed_payments"),
            },
            "retirement_election": rec.get("retirement_effects", {}),
            "tax_totals": rec.get("tax_totals", {}),
            "qbi_effects": rec.get("qbi_effects", {}),
            "deltas": rec.get("deltas", {}),
        }

    return {
        "result_id": result_id,
        "scenario_id": run["scenario_id"],
        "objective": objective,
        "summary": summary,
        "recommended_strategy": rec,
        "top_alternatives": run["alternatives"][:3],
        "estimated_payments_plan_id": run.get("estimated_payments_plan_id"),
        "rationale": rationale,
        "generated_at": _now_iso(),
    }


if __name__ == "__main__":
    mcp.run()
