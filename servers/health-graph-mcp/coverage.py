from __future__ import annotations

from helpers import (
    _contains_placeholder,
    _finish_run,
    _first_nonempty,
    _read_json_input,
    _row_to_dict,
    _start_run,
    _to_json,
    _validate_source_name,
)
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
    ok_response as _ok_response,
)


def register_coverage_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def ingest_coverage_artifacts(
        source_name: str,
        payload_json: str | dict | list,
        subject_id: int = 0,
    ) -> dict:
        """Ingest codified coverage artifacts and optional rule updates."""
        await ensure_initialized()

        try:
            _validate_source_name(source_name)
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        payload = _read_json_input(payload_json)
        pool = await get_pool()
        rows_written = 0
        skipped_placeholder = 0
        skipped_invalid = 0

        rules: list[dict] = []
        if isinstance(payload, dict):
            rules_raw = payload.get("benefit_rules")
            if isinstance(rules_raw, list):
                rules = [r for r in rules_raw if isinstance(r, dict)]
        elif isinstance(payload, list):
            rules = [r for r in payload if isinstance(r, dict)]

        async with pool.acquire() as conn:
            run_id = await _start_run(conn, source_name=source_name, run_type="coverage_artifact_ingest")
            try:
                for rule in rules:
                    if _contains_placeholder(rule):
                        skipped_placeholder += 1
                        continue

                    code_system = _first_nonempty(rule.get("code_system")) or "CPT"
                    code_value = _first_nonempty(rule.get("code_value"))
                    decision_default = _first_nonempty(rule.get("decision_default"))
                    if not code_value or not decision_default:
                        skipped_invalid += 1
                        continue
                    if str(code_value).strip().lower() == "unknown" or str(decision_default).strip().lower() == "unknown":
                        skipped_invalid += 1
                        continue

                    await conn.execute(
                        """INSERT INTO benefit_rules (
                               payer_name, plan_name, code_system, code_value, rule_type,
                               decision_default, requires_prior_auth, notes, active, metadata
                           ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
                           ON CONFLICT DO NOTHING""",
                        _first_nonempty(rule.get("payer_name")),
                        _first_nonempty(rule.get("plan_name")),
                        code_system,
                        code_value,
                        _first_nonempty(rule.get("rule_type")) or "coverage",
                        decision_default,
                        bool(rule.get("requires_prior_auth")),
                        _first_nonempty(rule.get("notes")),
                        bool(rule.get("active", True)),
                        _to_json(rule),
                    )
                    rows_written += 1

                await _finish_run(conn, run_id, "success", len(rules), rows_written)
                return _ok_response(
                    {
                    "ingestion_run_id": run_id,
                    "rows_read": len(rules),
                    "rows_written": rows_written,
                    "skipped_placeholder": skipped_placeholder,
                    "skipped_invalid": skipped_invalid,
                    "subject_id": subject_id or None,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", len(rules), rows_written, str(exc))
                return _error_response(
                    str(exc),
                    code="coverage_ingest_failed",
                    payload={
                        "ingestion_run_id": run_id,
                        "rows_written": rows_written,
                        "skipped_placeholder": skipped_placeholder,
                        "skipped_invalid": skipped_invalid,
                    },
                )

    @_tool
    async def evaluate_coverage(
        subject_id: int,
        code_system: str,
        code_value: str,
    ) -> dict:
        """Evaluate whether a code appears covered for a subject based on codified rules and active coverage."""
        await ensure_initialized()
        pool = await get_pool()

        async with pool.acquire() as conn:
            coverage = await conn.fetchrow(
                """SELECT *
                   FROM coverages
                   WHERE subject_id=$1
                     AND (status IS NULL OR status IN ('active', 'in-force', 'inforce'))
                     AND (end_date IS NULL OR end_date >= CURRENT_DATE)
                   ORDER BY id DESC
                   LIMIT 1""",
                subject_id,
            )

            rules = await conn.fetch(
                """SELECT *
                   FROM benefit_rules
                   WHERE active = TRUE
                     AND code_system = $1
                     AND code_value = $2
                   ORDER BY id DESC""",
                code_system,
                code_value,
            )

            decision = "unknown"
            required_pa = False
            reasons = []
            explanation = "No rule matched"

            if coverage is None:
                decision = "unknown"
                reasons.append("no_active_coverage")
                explanation = "No active coverage found for subject"
            elif rules:
                latest = rules[0]
                decision = latest["decision_default"] or "unknown"
                required_pa = bool(latest["requires_prior_auth"])
                reasons.append("rule_match")
                explanation = latest["notes"] or "Decision from benefit_rules"
            else:
                decision = "unknown"
                reasons.append("no_rule_match")
                explanation = "Active coverage found but no codified rule matched"

            det = await conn.fetchrow(
                """INSERT INTO coverage_determinations (
                       subject_id, coverage_id, code_system, code_value, decision,
                       required_prior_auth, reason_codes, explanation, supporting_refs, metadata
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9::jsonb,$10::jsonb)
                   RETURNING *""",
                subject_id,
                int(coverage["id"]) if coverage else None,
                code_system,
                code_value,
                decision,
                required_pa,
                _to_json(reasons),
                explanation,
                _to_json([]),
                _to_json({"rule_count": len(rules)}),
            )

        return _row_to_dict(det) or {}

    @_tool
    async def explain_coverage_determination(determination_id: int) -> dict:
        """Explain a prior coverage determination."""
        await ensure_initialized()
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM coverage_determinations WHERE id = $1",
                determination_id,
            )
        if row is None:
            return _error_response("determination not found", code="not_found")
        return _row_to_dict(row) or {}
