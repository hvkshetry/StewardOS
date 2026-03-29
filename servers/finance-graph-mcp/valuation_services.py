from __future__ import annotations

import hashlib
import json
from datetime import date

from jsonschema import ValidationError, validate

from stewardos_lib.constants import OCF_MINIMAL_SCHEMA
from stewardos_lib.db import float_or_none as _float_or_none, row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import (
    insert_valuation_observation as _insert_valuation_observation,
    normalize_currency_code as _normalize_currency_code,
)
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import error_response as _error_response

OCF_DEFAULT_VERSION = "1.2.0"
_PROMOTION_MODES = {"auto", "never", "force"}


def _normalize_promotion_mode(promote_to_current: str) -> str:
    normalized = (promote_to_current or "auto").strip().lower()
    if normalized not in _PROMOTION_MODES:
        raise ValueError("promote_to_current must be one of: auto, never, force")
    return normalized


def _confidence_value(value) -> float | None:
    if value is None:
        return None
    return float(value)


def _rows_affected(command_tag: str) -> int:
    parts = (command_tag or "").strip().split()
    if not parts:
        return 0
    try:
        return int(parts[-1])
    except (TypeError, ValueError):
        return 0


def _xbrl_fact_fingerprint(fact: dict) -> str:
    normalized = {
        "concept_qname": str(
            fact.get("concept_qname") or fact.get("concept") or fact.get("qname") or ""
        ).strip(),
        "context_ref": str(fact.get("context_ref") or "").strip(),
        "unit_ref": str(fact.get("unit_ref") or "").strip(),
        "period_start": str(fact.get("period_start") or "").strip(),
        "period_end": str(fact.get("period_end") or "").strip(),
        "instant_date": str(fact.get("instant_date") or "").strip(),
        "fact_value_text": str(fact.get("fact_value_text") or fact.get("value") or ""),
        "fact_value_numeric": _float_or_none(
            fact.get("fact_value_numeric") if "fact_value_numeric" in fact else fact.get("value")
        ),
        "decimals": str(fact.get("decimals") or ""),
        "precision": str(fact.get("precision") or ""),
        "dimensions": fact.get("dimensions") if isinstance(fact.get("dimensions"), dict) else {},
        "metadata": fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {},
    }
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _current_valuation_row(conn, asset_id: int):
    return await conn.fetchrow(
        """SELECT vo.id AS observation_id,
                  vo.valuation_date,
                  vo.confidence_score
           FROM finance.valuation_observations vo
           WHERE vo.asset_id = $1 AND vo.is_current = true""",
        asset_id,
    )


def _should_promote_current(existing_row, candidate_row, promote_mode: str) -> bool:
    if promote_mode == "never":
        return False
    if promote_mode == "force":
        return True
    if not existing_row or existing_row.get("observation_id") is None:
        return True

    existing_date = existing_row.get("valuation_date")
    candidate_date = candidate_row.get("valuation_date")
    if candidate_date and existing_date:
        if candidate_date > existing_date:
            return True
        if candidate_date < existing_date:
            return False

    existing_confidence = _confidence_value(existing_row.get("confidence_score"))
    candidate_confidence = _confidence_value(candidate_row.get("confidence_score"))
    if candidate_confidence is None:
        return False
    if existing_confidence is None:
        return True
    return candidate_confidence > existing_confidence


async def promote_current_valuation_observation(
    conn,
    *,
    asset_id: int,
    observation_row,
    promote_to_current: str = "auto",
) -> dict[str, int | bool | None]:
    normalized_mode = _normalize_promotion_mode(promote_to_current)
    current_row = await _current_valuation_row(conn, asset_id)
    should_promote = _should_promote_current(current_row, observation_row, normalized_mode)
    current_observation_id = (
        int(current_row["observation_id"])
        if current_row is not None
        else None
    )

    if should_promote:
        current_observation_id = int(observation_row["id"])
        # Clear old is_current, set new one — single transaction
        await conn.execute(
            """UPDATE finance.valuation_observations
               SET is_current = false
               WHERE asset_id = $1 AND is_current = true""",
            asset_id,
        )
        await conn.execute(
            """UPDATE finance.valuation_observations
               SET is_current = true
               WHERE id = $1""",
            current_observation_id,
        )

    return {
        "promoted_to_current": should_promote,
        "current_observation_id": current_observation_id,
    }


def _validate_ocf_payload(payload: dict | None) -> dict:
    if not payload:
        return {"valid": False, "errors": ["Document must be a JSON object"]}

    errors: list[str] = []
    try:
        validate(instance=payload, schema=OCF_MINIMAL_SCHEMA)
    except ValidationError as exc:
        errors.append(str(exc))

    ocf_version = payload.get("ocf_version")
    if isinstance(ocf_version, str):
        if not ocf_version.strip():
            errors.append("ocf_version must be non-empty")
    else:
        errors.append("ocf_version must be a string")

    return {
        "valid": len(errors) == 0,
        "ocf_version": ocf_version,
        "errors": errors,
        "expected_version_default": OCF_DEFAULT_VERSION,
    }


def _statement_table_name(statement_type: str) -> str | None:
    normalized = (statement_type or "").strip().lower()
    mapping = {
        "income_statement": "income_statement_facts",
        "pl": "income_statement_facts",
        "p&l": "income_statement_facts",
        "cash_flow_statement": "cash_flow_statement_facts",
        "cash_flow": "cash_flow_statement_facts",
        "cfs": "cash_flow_statement_facts",
        "balance_sheet": "balance_sheet_facts",
        "bs": "balance_sheet_facts",
    }
    return mapping.get(normalized)


async def list_valuation_methods(get_pool):
    pool = await get_pool()
    rows = await pool.fetch(
        """SELECT code, name, description, created_at
           FROM valuation_methods
           ORDER BY code"""
    )
    return _rows_to_list(rows)


async def record_valuation_observation(
    get_pool,
    asset_id: int,
    method_code: str,
    value_amount: float,
    value_currency: str = "USD",
    source: str = "manual",
    valuation_date: str | None = None,
    confidence_score: float | None = None,
    notes: str | None = None,
    evidence: dict | str | None = None,
    promote_to_current: str = "auto",
):
    pool = await get_pool()
    try:
        normalized_mode = _normalize_promotion_mode(promote_to_current)
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")
    normalized_currency = _normalize_currency_code(value_currency)
    if not normalized_currency:
        return _error_response(
            "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)",
            code="validation_error",
        )

    vd = date.fromisoformat(valuation_date) if valuation_date else date.today()
    evidence_payload = _coerce_json_input(evidence)
    async with pool.acquire() as conn:
        async with conn.transaction():
            exists = await conn.fetchval("SELECT 1 FROM assets WHERE id = $1", asset_id)
            if not exists:
                return _error_response(f"Asset {asset_id} not found", code="not_found")
            try:
                row = await _insert_valuation_observation(
                    pool=conn,
                    asset_id=asset_id,
                    method_code=method_code,
                    source=source,
                    value_amount=value_amount,
                    value_currency=normalized_currency,
                    valuation_date=vd,
                    confidence_score=confidence_score,
                    notes=notes,
                    evidence=evidence_payload,
                )
                promotion = await promote_current_valuation_observation(
                    conn,
                    asset_id=asset_id,
                    observation_row=row,
                    promote_to_current=normalized_mode,
                )
            except ValueError as exc:
                return _error_response(str(exc), code="validation_error")

    payload = _row_to_dict(row)
    payload.update(promotion)
    return payload


async def list_valuation_observations(
    get_pool,
    asset_id: int | None = None,
    limit: int = 100,
):
    pool = await get_pool()
    cap = max(1, min(limit, 500))
    if asset_id:
        rows = await pool.fetch(
            """SELECT vo.*, a.name AS asset_name
               FROM valuation_observations vo
               JOIN assets a ON vo.asset_id = a.id
               WHERE vo.asset_id = $1
               ORDER BY vo.valuation_date DESC, vo.id DESC
               LIMIT $2""",
            asset_id,
            cap,
        )
    else:
        rows = await pool.fetch(
            """SELECT vo.*, a.name AS asset_name
               FROM valuation_observations vo
               JOIN assets a ON vo.asset_id = a.id
               ORDER BY vo.valuation_date DESC, vo.id DESC
               LIMIT $1""",
            cap,
        )
    return _rows_to_list(rows)


async def set_manual_comp_valuation(
    get_pool,
    asset_id: int,
    value_amount: float,
    value_currency: str = "USD",
    valuation_date: str | None = None,
    confidence_score: float | None = None,
    notes: str | None = None,
    comps: list[dict] | str | None = None,
    promote_to_current: str = "auto",
):
    pool = await get_pool()
    normalized_currency = _normalize_currency_code(value_currency)
    if not normalized_currency:
        return _error_response(
            "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)",
            code="validation_error",
        )

    vd = date.fromisoformat(valuation_date) if valuation_date else date.today()
    try:
        normalized_mode = _normalize_promotion_mode(promote_to_current)
    except ValueError as exc:
        return _error_response(str(exc), code="validation_error")

    comps_payload = []
    if isinstance(comps, list):
        comps_payload = comps
    elif isinstance(comps, str):
        try:
            parsed = json.loads(comps)
            if isinstance(parsed, list):
                comps_payload = parsed
        except json.JSONDecodeError:
            comps_payload = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                observation = await _insert_valuation_observation(
                    pool=conn,
                    asset_id=asset_id,
                    method_code="manual_comp",
                    source="user_manual",
                    value_amount=value_amount,
                    value_currency=normalized_currency,
                    valuation_date=vd,
                    confidence_score=confidence_score,
                    notes=notes,
                    evidence={"comps_count": len(comps_payload)},
                )
            except ValueError as exc:
                return _error_response(str(exc), code="validation_error")
            observation_id = int(observation["id"])

            inserted_comps = 0
            for comp in comps_payload:
                if not isinstance(comp, dict):
                    continue
                comp_date = None
                raw_date = comp.get("valuation_date")
                if isinstance(raw_date, str) and raw_date:
                    try:
                        comp_date = date.fromisoformat(raw_date)
                    except ValueError:
                        comp_date = None
                await conn.execute(
                    """INSERT INTO valuation_comps (
                           valuation_observation_id, comp_identifier, address, city, state_code,
                           country_code, valuation_amount, valuation_currency, valuation_date,
                           distance_km, adjustment_notes, raw_data
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
                    observation_id,
                    comp.get("comp_identifier") or comp.get("id"),
                    comp.get("address"),
                    comp.get("city"),
                    comp.get("state_code") or comp.get("state"),
                    comp.get("country_code") or comp.get("country"),
                    _float_or_none(comp.get("valuation_amount") or comp.get("value")),
                    _normalize_currency_code(comp.get("valuation_currency") or comp.get("currency")) or normalized_currency,
                    comp_date,
                    _float_or_none(comp.get("distance_km") or comp.get("distance")),
                    comp.get("adjustment_notes"),
                    json.dumps(comp),
                )
                inserted_comps += 1
            promotion = await promote_current_valuation_observation(
                conn,
                asset_id=asset_id,
                observation_row=observation,
                promote_to_current=normalized_mode,
            )

    return {
        "observation_id": observation_id,
        "asset_id": asset_id,
        "comps_inserted": inserted_comps,
        **promotion,
    }


async def upsert_financial_statement_period(
    get_pool,
    asset_id: int,
    period_start: str,
    period_end: str,
    fiscal_year: int | None = None,
    fiscal_period: str | None = None,
    statement_currency: str = "USD",
    source: str = "manual",
    reporting_period_id: int | None = None,
):
    pool = await get_pool()
    normalized_statement_currency = _normalize_currency_code(statement_currency)
    if not normalized_statement_currency:
        return _error_response(
            "statement_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)",
            code="validation_error",
        )
    ps = date.fromisoformat(period_start)
    pe = date.fromisoformat(period_end)

    if reporting_period_id:
        row = await pool.fetchrow(
            """UPDATE reporting_periods
               SET asset_id = $1, period_start = $2, period_end = $3, fiscal_year = $4,
                   fiscal_period = $5, statement_currency = $6, source = $7, updated_at = now()
               WHERE id = $8
               RETURNING *""",
            asset_id,
            ps,
            pe,
            fiscal_year,
            fiscal_period,
            normalized_statement_currency,
            source,
            reporting_period_id,
        )
    else:
        existing_id = await pool.fetchval(
            """SELECT id
               FROM reporting_periods
               WHERE asset_id = $1
                 AND period_start = $2
                 AND period_end = $3
                 AND COALESCE(fiscal_period, '') = COALESCE($4, '')""",
            asset_id,
            ps,
            pe,
            fiscal_period,
        )
        if existing_id:
            row = await pool.fetchrow(
                """UPDATE reporting_periods
                   SET fiscal_year = $1, statement_currency = $2, source = $3, updated_at = now()
                   WHERE id = $4
                   RETURNING *""",
                fiscal_year,
                normalized_statement_currency,
                source,
                existing_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO reporting_periods (
                       asset_id, period_start, period_end, fiscal_year, fiscal_period,
                       statement_currency, source
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                   RETURNING *""",
                asset_id,
                ps,
                pe,
                fiscal_year,
                fiscal_period,
                normalized_statement_currency,
                source,
            )
    return _row_to_dict(row)


async def upsert_statement_line_items(
    get_pool,
    reporting_period_id: int,
    statement_type: str,
    line_items: dict | str,
    source: str = "manual",
    value_currency: str = "USD",
    overwrite: bool = True,
):
    pool = await get_pool()
    normalized_value_currency = _normalize_currency_code(value_currency)
    if not normalized_value_currency:
        return _error_response(
            "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)",
            code="validation_error",
        )

    table_name = _statement_table_name(statement_type)
    if not table_name:
        return _error_response(
            f"Unsupported statement_type: {statement_type}",
            code="validation_error",
            payload={"valid_values": ["income_statement", "cash_flow_statement", "balance_sheet"]},
        )

    payload = _coerce_json_input(line_items)
    if not payload:
        return _error_response(
            "line_items must be a non-empty dict or JSON object string",
            code="validation_error",
        )

    inserted = 0
    updated = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for code, raw in payload.items():
                if not isinstance(code, str) or not code.strip():
                    continue
                line_item_code = code.strip()
                line_item_label = None
                metadata = {}
                numeric_value = None

                if isinstance(raw, dict):
                    line_item_label = raw.get("label")
                    metadata = raw.get("metadata", {}) if isinstance(raw.get("metadata"), dict) else {}
                    numeric_value = _float_or_none(
                        raw.get("value_amount") if "value_amount" in raw else raw.get("value")
                    )
                else:
                    numeric_value = _float_or_none(raw)

                if numeric_value is None:
                    continue

                if overwrite:
                    await conn.execute(
                        f"""INSERT INTO {table_name} (
                                reporting_period_id, line_item_code, line_item_label,
                                value_amount, value_currency, source, metadata
                            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                            ON CONFLICT (reporting_period_id, line_item_code, source) DO UPDATE SET
                                line_item_label = EXCLUDED.line_item_label,
                                value_amount = EXCLUDED.value_amount,
                                value_currency = EXCLUDED.value_currency,
                                metadata = EXCLUDED.metadata,
                                updated_at = now()""",
                        reporting_period_id,
                        line_item_code,
                        line_item_label,
                        numeric_value,
                        normalized_value_currency,
                        source,
                        json.dumps(metadata),
                    )
                    updated += 1
                else:
                    command_tag = await conn.execute(
                        f"""INSERT INTO {table_name} (
                                reporting_period_id, line_item_code, line_item_label,
                                value_amount, value_currency, source, metadata
                            ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                            ON CONFLICT (reporting_period_id, line_item_code, source) DO NOTHING""",
                        reporting_period_id,
                        line_item_code,
                        line_item_label,
                        numeric_value,
                        normalized_value_currency,
                        source,
                        json.dumps(metadata),
                    )
                    inserted += _rows_affected(command_tag)

    return {
        "statement_type": statement_type,
        "table_name": table_name,
        "rows_processed": len(payload),
        "rows_updated_or_upserted": updated,
        "rows_inserted_no_overwrite_mode": inserted,
    }


async def upsert_xbrl_facts_core(
    get_pool,
    accession_number: str,
    facts: list[dict] | str,
    asset_id: int | None = None,
    filing_date: str | None = None,
    cik: str | None = None,
    ticker: str | None = None,
    source: str = "sec-edgar",
):
    pool = await get_pool()
    fd = date.fromisoformat(filing_date) if filing_date else None

    facts_payload = facts if isinstance(facts, list) else []
    if isinstance(facts, str):
        try:
            parsed = json.loads(facts)
            if isinstance(parsed, list):
                facts_payload = parsed
        except json.JSONDecodeError:
            facts_payload = []
    if not facts_payload:
        return _error_response(
            "facts must be a non-empty list or JSON list string",
            code="validation_error",
        )

    async with pool.acquire() as conn:
        async with conn.transaction():
            report = await conn.fetchrow(
                """INSERT INTO xbrl_reports (asset_id, accession_number, cik, ticker, filing_date, source)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (accession_number) DO UPDATE SET
                       asset_id = COALESCE(EXCLUDED.asset_id, xbrl_reports.asset_id),
                       cik = COALESCE(EXCLUDED.cik, xbrl_reports.cik),
                       ticker = COALESCE(EXCLUDED.ticker, xbrl_reports.ticker),
                       filing_date = COALESCE(EXCLUDED.filing_date, xbrl_reports.filing_date),
                       source = EXCLUDED.source
                   RETURNING id""",
                asset_id,
                accession_number,
                cik,
                ticker,
                fd,
                source,
            )
            report_id = int(report["id"])
            await conn.execute("DELETE FROM xbrl_facts WHERE xbrl_report_id = $1", report_id)
            await conn.execute("DELETE FROM xbrl_contexts WHERE xbrl_report_id = $1", report_id)
            await conn.execute("DELETE FROM xbrl_units WHERE xbrl_report_id = $1", report_id)

            inserted_facts = 0
            for fact in facts_payload:
                if not isinstance(fact, dict):
                    continue
                concept_qname = fact.get("concept_qname") or fact.get("concept") or fact.get("qname") or ""
                concept_qname = concept_qname.strip()
                if not concept_qname:
                    continue

                concept = await conn.fetchrow(
                    """INSERT INTO xbrl_concepts (
                           concept_qname, namespace, local_name, label, data_type, balance, period_type
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                       ON CONFLICT (concept_qname) DO UPDATE SET
                           label = COALESCE(EXCLUDED.label, xbrl_concepts.label),
                           data_type = COALESCE(EXCLUDED.data_type, xbrl_concepts.data_type),
                           balance = COALESCE(EXCLUDED.balance, xbrl_concepts.balance),
                           period_type = COALESCE(EXCLUDED.period_type, xbrl_concepts.period_type)
                       RETURNING id""",
                    concept_qname,
                    fact.get("namespace"),
                    fact.get("local_name"),
                    fact.get("label"),
                    fact.get("data_type"),
                    fact.get("balance"),
                    fact.get("period_type"),
                )
                concept_id = int(concept["id"])

                context_id = None
                context_ref = fact.get("context_ref")
                if isinstance(context_ref, str) and context_ref.strip():
                    ps = None
                    pe = None
                    inst = None
                    try:
                        if fact.get("period_start"):
                            ps = date.fromisoformat(str(fact.get("period_start")))
                        if fact.get("period_end"):
                            pe = date.fromisoformat(str(fact.get("period_end")))
                        if fact.get("instant_date"):
                            inst = date.fromisoformat(str(fact.get("instant_date")))
                    except ValueError:
                        ps = None
                        pe = None
                        inst = None
                    context = await conn.fetchrow(
                        """INSERT INTO xbrl_contexts (
                               xbrl_report_id, context_ref, entity_identifier,
                               period_start, period_end, instant_date, dimensions
                           ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                           ON CONFLICT (xbrl_report_id, context_ref) DO UPDATE SET
                               period_start = COALESCE(EXCLUDED.period_start, xbrl_contexts.period_start),
                               period_end = COALESCE(EXCLUDED.period_end, xbrl_contexts.period_end),
                               instant_date = COALESCE(EXCLUDED.instant_date, xbrl_contexts.instant_date),
                               dimensions = EXCLUDED.dimensions
                           RETURNING id""",
                        report_id,
                        context_ref.strip(),
                        fact.get("entity_identifier"),
                        ps,
                        pe,
                        inst,
                        json.dumps(fact.get("dimensions") if isinstance(fact.get("dimensions"), dict) else {}),
                    )
                    context_id = int(context["id"])

                unit_id = None
                unit_ref = fact.get("unit_ref")
                if isinstance(unit_ref, str) and unit_ref.strip():
                    unit = await conn.fetchrow(
                        """INSERT INTO xbrl_units (xbrl_report_id, unit_ref, measure, numerator, denominator)
                           VALUES ($1,$2,$3,$4,$5)
                           ON CONFLICT (xbrl_report_id, unit_ref) DO UPDATE SET
                               measure = COALESCE(EXCLUDED.measure, xbrl_units.measure),
                               numerator = COALESCE(EXCLUDED.numerator, xbrl_units.numerator),
                               denominator = COALESCE(EXCLUDED.denominator, xbrl_units.denominator)
                           RETURNING id""",
                        report_id,
                        unit_ref.strip(),
                        fact.get("measure"),
                        fact.get("numerator"),
                        fact.get("denominator"),
                    )
                    unit_id = int(unit["id"])

                fact_value_numeric = _float_or_none(
                    fact.get("fact_value_numeric") if "fact_value_numeric" in fact else fact.get("value")
                )
                fact_value_text = fact.get("fact_value_text")
                if fact_value_text is None and fact.get("value") is not None:
                    fact_value_text = str(fact.get("value"))

                await conn.execute(
                    """INSERT INTO xbrl_facts (
                           xbrl_report_id, concept_id, context_id, unit_id, fact_fingerprint,
                           fact_value_text, fact_value_numeric, decimals, precision, metadata
                       ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                    report_id,
                    concept_id,
                    context_id,
                    unit_id,
                    _xbrl_fact_fingerprint(fact),
                    fact_value_text,
                    fact_value_numeric,
                    fact.get("decimals"),
                    fact.get("precision"),
                    json.dumps(fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}),
                )
                inserted_facts += 1

    return {
        "xbrl_report_id": report_id,
        "accession_number": accession_number,
        "facts_ingested": inserted_facts,
    }


async def validate_ocf_document(document: dict | str):
    payload = _coerce_json_input(document)
    return _validate_ocf_payload(payload)


async def ingest_ocf_document(
    get_pool,
    document: dict | str,
    asset_id: int | None = None,
    run_validation: bool = True,
):
    pool = await get_pool()
    payload = _coerce_json_input(document)
    if not payload:
        return _error_response("Document must be a JSON object", code="validation_error")

    validation_status = "unknown"
    validation_errors: list[str] = []
    if run_validation:
        validation_result = _validate_ocf_payload(payload)
        validation_status = "valid" if validation_result.get("valid") else "invalid"
        validation_errors = validation_result.get("errors", [])

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    ocf_version = payload.get("ocf_version")

    async with pool.acquire() as conn:
        async with conn.transaction():
            document_row = await conn.fetchrow(
                """INSERT INTO ocf_documents (asset_id, ocf_version, document_hash, validation_status, validation_errors, payload)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (document_hash) DO UPDATE SET
                       asset_id = COALESCE(EXCLUDED.asset_id, ocf_documents.asset_id),
                       ocf_version = COALESCE(EXCLUDED.ocf_version, ocf_documents.ocf_version),
                       validation_status = EXCLUDED.validation_status,
                       validation_errors = EXCLUDED.validation_errors,
                       payload = EXCLUDED.payload
                   RETURNING id""",
                asset_id,
                ocf_version if isinstance(ocf_version, str) else None,
                digest,
                validation_status,
                json.dumps(validation_errors),
                json.dumps(payload),
            )
            document_id = int(document_row["id"])

            await conn.execute("DELETE FROM ocf_instruments WHERE ocf_document_id = $1", document_id)
            await conn.execute("DELETE FROM ocf_positions WHERE ocf_document_id = $1", document_id)

            instruments = payload.get("instruments")
            if not isinstance(instruments, list):
                instruments = []
            positions = payload.get("positions")
            if not isinstance(positions, list):
                positions = []

            instrument_count = 0
            for instrument in instruments:
                if not isinstance(instrument, dict):
                    continue
                instrument_id = instrument.get("id") or instrument.get("instrument_id") or instrument.get("security_id")
                if not instrument_id:
                    continue
                await conn.execute(
                    """INSERT INTO ocf_instruments (
                           ocf_document_id, instrument_id, instrument_type, security_name, payload
                       ) VALUES ($1,$2,$3,$4,$5)
                       ON CONFLICT (ocf_document_id, instrument_id) DO UPDATE SET
                           instrument_type = EXCLUDED.instrument_type,
                           security_name = EXCLUDED.security_name,
                           payload = EXCLUDED.payload""",
                    document_id,
                    str(instrument_id),
                    instrument.get("type") or instrument.get("instrument_type"),
                    instrument.get("name") or instrument.get("security_name"),
                    json.dumps(instrument),
                )
                instrument_count += 1

            position_count = 0
            for position in positions:
                if not isinstance(position, dict):
                    continue
                await conn.execute(
                    """INSERT INTO ocf_positions (
                           ocf_document_id, instrument_id, stakeholder_name, quantity, ownership_pct, payload
                       ) VALUES ($1,$2,$3,$4,$5,$6)""",
                    document_id,
                    position.get("instrument_id") or position.get("security_id"),
                    position.get("stakeholder_name") or position.get("holder_name"),
                    _float_or_none(position.get("quantity")),
                    _float_or_none(position.get("ownership_pct")),
                    json.dumps(position),
                )
                position_count += 1

    return {
        "ocf_document_id": document_id,
        "document_hash": digest,
        "validation_status": validation_status,
        "validation_errors": validation_errors,
        "instruments_ingested": instrument_count,
        "positions_ingested": position_count,
    }


async def get_ocf_positions(
    get_pool,
    ocf_document_id: int | None = None,
    asset_id: int | None = None,
    limit: int = 500,
):
    pool = await get_pool()
    cap = max(1, min(limit, 2000))
    if ocf_document_id:
        rows = await pool.fetch(
            """SELECT p.*, d.asset_id, d.ocf_version, d.created_at AS document_created_at
               FROM ocf_positions p
               JOIN ocf_documents d ON p.ocf_document_id = d.id
               WHERE p.ocf_document_id = $1
               ORDER BY p.id
               LIMIT $2""",
            ocf_document_id,
            cap,
        )
    elif asset_id:
        rows = await pool.fetch(
            """SELECT p.*, d.asset_id, d.ocf_version, d.created_at AS document_created_at
               FROM ocf_positions p
               JOIN ocf_documents d ON p.ocf_document_id = d.id
               WHERE d.asset_id = $1
               ORDER BY p.id
               LIMIT $2""",
            asset_id,
            cap,
        )
    else:
        rows = await pool.fetch(
            """SELECT p.*, d.asset_id, d.ocf_version, d.created_at AS document_created_at
               FROM ocf_positions p
               JOIN ocf_documents d ON p.ocf_document_id = d.id
               ORDER BY p.id DESC
               LIMIT $1""",
            cap,
        )
    return _rows_to_list(rows)
