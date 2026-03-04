"""MCP server for learner records and development control-plane operations."""

import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
from mcp.server.fastmcp import FastMCP

from seed_data import (
    seed_activity_catalog,
    seed_learner_milestone_statuses,
    seed_milestone_definitions,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://family_edu:changeme@localhost:5434/family_edu"
)
SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

mcp = FastMCP(
    "family-edu-mcp",
    instructions=(
        "Learner records and development control-plane server. Tracks learner identity, "
        "enrollments, linked evidence artifacts, assessments, metric observations, goals, "
        "and structured weekly planning."
    ),
)

_pool: asyncpg.Pool | None = None
_init_lock = asyncio.Lock()
_initialized = False


def _opt_id(value: int | None) -> int | None:
    if value is None:
        return None
    return value if value > 0 else None


def _rows_affected(status: str) -> int:
    try:
        return int(status.split()[-1])
    except Exception:
        return 0


def _normalize_date(value: str, field_name: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid {field_name} format. Use YYYY-MM-DD.")


def _normalize_datetime(value: str, field_name: str) -> str:
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid {field_name} format. Use ISO datetime or YYYY-MM-DD.") from exc


def _child_age_months(dob_str: str) -> int:
    dob = datetime.strptime(dob_str, "%Y-%m-%d")
    today = datetime.now()
    return (today.year - dob.year) * 12 + (today.month - dob.month)


def _row_to_dict(row: asyncpg.Record | None) -> dict | None:
    if row is None:
        return None

    payload: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, (date, datetime)):
            payload[key] = value.isoformat()
        elif isinstance(value, Decimal):
            payload[key] = float(value)
        elif isinstance(value, str):
            trimmed = value.strip()
            if (trimmed.startswith("{") and trimmed.endswith("}")) or (
                trimmed.startswith("[") and trimmed.endswith("]")
            ):
                try:
                    payload[key] = json.loads(trimmed)
                    continue
                except json.JSONDecodeError:
                    pass
            payload[key] = value
        else:
            payload[key] = value
    return payload


def _rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict]:
    return [_row_to_dict(row) for row in rows if row is not None]


def _title_from_code(code: str) -> str:
    return " ".join(part.capitalize() for part in code.replace("-", "_").split("_"))


def _heuristic_extract(raw_text: str) -> dict:
    if not raw_text.strip():
        return {"signals": [], "numbers": [], "grades": []}

    numbers = [float(match.group(0)) for match in re.finditer(r"\b\d+(?:\.\d+)?\b", raw_text)]
    percentages = [float(match.group(1)) for match in re.finditer(r"\b(\d{1,3}(?:\.\d+)?)%", raw_text)]
    grade_pairs = []
    for match in re.finditer(r"([A-Za-z ]{2,40})\s*[:\-]\s*([A-F][+-]?|\d{1,3}(?:\.\d+)?)", raw_text):
        grade_pairs.append({"label": match.group(1).strip(), "value": match.group(2).strip()})

    signals = []
    if percentages:
        signals.append("percentages_detected")
    if grade_pairs:
        signals.append("grade_like_pairs_detected")
    if len(numbers) >= 3:
        signals.append("multi_numeric_payload")

    return {
        "signals": signals,
        "numbers": numbers[:100],
        "percentages": percentages[:100],
        "grades": grade_pairs[:100],
        "raw_length": len(raw_text),
    }


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=8,
            server_settings={"search_path": "family_edu,public"},
        )
    return _pool


async def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return

    async with _init_lock:
        if _initialized:
            return

        pool = await _get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(SCHEMA_SQL)
                await seed_milestone_definitions(conn)
                await seed_activity_catalog(conn)
                await seed_learner_milestone_statuses(conn)

        _initialized = True


async def _fetch_learner_or_none(conn: asyncpg.Connection, learner_id: int) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM learners WHERE id = $1", learner_id)
    return _row_to_dict(row)


@mcp.tool()
async def create_learner(
    display_name: str,
    date_of_birth: str,
    metadata: dict | None = None,
) -> dict:
    """Create a learner profile in the canonical records store."""
    if metadata is None:
        metadata = {}

    try:
        dob = _normalize_date(date_of_birth, "date_of_birth")
    except ValueError as exc:
        return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO learners (display_name, date_of_birth, metadata) "
                "VALUES ($1, $2::text::date, $3::jsonb) "
                "ON CONFLICT (display_name, date_of_birth) "
                "DO UPDATE SET metadata = learners.metadata || EXCLUDED.metadata, updated_at = NOW() "
                "RETURNING *",
                display_name,
                dob,
                json.dumps(metadata, ensure_ascii=False),
            )
            learner = _row_to_dict(row)
            assert learner is not None
            await seed_learner_milestone_statuses(conn, int(learner["id"]))

    learner["age_months"] = _child_age_months(learner["date_of_birth"])
    return learner


@mcp.tool()
async def list_learners() -> list[dict]:
    """List all learners with current age in months."""
    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM learners ORDER BY display_name")

    learners = _rows_to_dicts(rows)
    for learner in learners:
        learner["age_months"] = _child_age_months(learner["date_of_birth"])
    return learners


@mcp.tool()
async def get_learner_profile(learner_id: int) -> dict:
    """Return learner profile, milestone status summary, and active context."""
    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        enrollment_rows = await conn.fetch(
            "SELECT e.*, i.name AS institution_name, p.name AS program_name, t.label AS term_label "
            "FROM enrollments e "
            "LEFT JOIN institutions i ON i.id = e.institution_id "
            "LEFT JOIN programs p ON p.id = e.program_id "
            "LEFT JOIN terms t ON t.id = e.term_id "
            "WHERE e.learner_id = $1 ORDER BY COALESCE(e.start_date, DATE '1900-01-01') DESC",
            learner_id,
        )

        milestone_stats = await conn.fetchrow(
            "SELECT "
            "COUNT(*) FILTER (WHERE status = 'achieved') AS achieved_count, "
            "COUNT(*) FILTER (WHERE status = 'pending') AS pending_count, "
            "COUNT(*) FILTER (WHERE status = 'not_applicable') AS not_applicable_count "
            "FROM learner_milestone_status WHERE learner_id = $1",
            learner_id,
        )

        goal_stats = await conn.fetchrow(
            "SELECT "
            "COUNT(*) FILTER (WHERE status IN ('open', 'in_progress')) AS open_goals, "
            "COUNT(*) FILTER (WHERE status = 'completed') AS completed_goals "
            "FROM goals WHERE learner_id = $1",
            learner_id,
        )

        artifact_stats_rows = await conn.fetch(
            "SELECT review_status, COUNT(*) AS count FROM artifacts "
            "WHERE learner_id = $1 GROUP BY review_status ORDER BY review_status",
            learner_id,
        )

    learner["age_months"] = _child_age_months(learner["date_of_birth"])
    return {
        "learner": learner,
        "enrollments": _rows_to_dicts(enrollment_rows),
        "milestone_summary": _row_to_dict(milestone_stats),
        "goal_summary": _row_to_dict(goal_stats),
        "artifact_summary": _rows_to_dicts(artifact_stats_rows),
    }


@mcp.tool()
async def list_enrollments(learner_id: int = 0, active_only: bool = True) -> list[dict]:
    """List enrollments across learners or for one learner."""
    await _ensure_initialized()
    pool = await _get_pool()

    query = (
        "SELECT e.*, l.display_name AS learner_name, i.name AS institution_name, "
        "p.name AS program_name, t.label AS term_label "
        "FROM enrollments e "
        "JOIN learners l ON l.id = e.learner_id "
        "LEFT JOIN institutions i ON i.id = e.institution_id "
        "LEFT JOIN programs p ON p.id = e.program_id "
        "LEFT JOIN terms t ON t.id = e.term_id "
        "WHERE 1=1"
    )
    params: list[Any] = []

    if learner_id > 0:
        params.append(learner_id)
        query += f" AND e.learner_id = ${len(params)}"
    if active_only:
        query += " AND e.enrollment_status = 'active'"

    query += " ORDER BY COALESCE(e.start_date, DATE '1900-01-01') DESC, e.id DESC"

    await _ensure_initialized()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return _rows_to_dicts(rows)


@mcp.tool()
async def search_artifacts(
    learner_id: int = 0,
    query: str = "",
    artifact_type: str = "",
    review_status: str = "",
    limit: int = 20,
) -> list[dict]:
    """Search linked evidence artifacts and metadata."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT a.*, l.display_name AS learner_name, i.name AS institution_name, "
        "p.name AS program_name, t.label AS term_label "
        "FROM artifacts a "
        "JOIN learners l ON l.id = a.learner_id "
        "LEFT JOIN institutions i ON i.id = a.institution_id "
        "LEFT JOIN programs p ON p.id = a.program_id "
        "LEFT JOIN terms t ON t.id = a.term_id "
        "WHERE 1=1"
    )
    params: list[Any] = []

    if learner_id > 0:
        params.append(learner_id)
        sql += f" AND a.learner_id = ${len(params)}"

    if artifact_type:
        params.append(artifact_type)
        sql += f" AND a.artifact_type = ${len(params)}"

    if review_status:
        params.append(review_status)
        sql += f" AND a.review_status = ${len(params)}"

    if query:
        params.append(f"%{query}%")
        sql += (
            f" AND (COALESCE(a.title, '') ILIKE ${len(params)} "
            f"OR COALESCE(a.summary, '') ILIKE ${len(params)} "
            f"OR COALESCE(a.source_metadata::text, '') ILIKE ${len(params)})"
        )

    params.append(max(1, min(limit, 200)))
    sql += f" ORDER BY COALESCE(a.document_date, DATE '1900-01-01') DESC, a.id DESC LIMIT ${len(params)}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return _rows_to_dicts(rows)


@mcp.tool()
async def link_paperless_document(
    learner_id: int,
    paperless_document_id: int,
    artifact_type: str,
    document_date: str = "",
    review_status: str = "pending",
    title: str = "",
    summary: str = "",
    institution_id: int = 0,
    program_id: int = 0,
    term_id: int = 0,
    artifact_link: str = "",
    source_system: str = "paperless",
    source_metadata: dict | None = None,
) -> dict:
    """Create or update evidence linkage to a Paperless document."""
    if source_metadata is None:
        source_metadata = {}

    if document_date:
        try:
            document_date = _normalize_date(document_date, "document_date")
        except ValueError as exc:
            return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        row = await conn.fetchrow(
            "INSERT INTO artifacts ("
            "learner_id, artifact_type, source_system, paperless_document_id, institution_id, "
            "program_id, term_id, document_date, review_status, title, summary, artifact_link, source_metadata"
            ") VALUES ("
            "$1, $2, $3, $4, $5, $6, $7, NULLIF($8, '')::date, $9, NULLIF($10, ''), NULLIF($11, ''), "
            "NULLIF($12, ''), $13::jsonb"
            ") ON CONFLICT (source_system, paperless_document_id) DO UPDATE SET "
            "learner_id = EXCLUDED.learner_id, "
            "artifact_type = EXCLUDED.artifact_type, "
            "institution_id = EXCLUDED.institution_id, "
            "program_id = EXCLUDED.program_id, "
            "term_id = EXCLUDED.term_id, "
            "document_date = EXCLUDED.document_date, "
            "review_status = EXCLUDED.review_status, "
            "title = EXCLUDED.title, "
            "summary = EXCLUDED.summary, "
            "artifact_link = EXCLUDED.artifact_link, "
            "source_metadata = artifacts.source_metadata || EXCLUDED.source_metadata, "
            "updated_at = NOW() "
            "RETURNING *",
            learner_id,
            artifact_type,
            source_system,
            paperless_document_id,
            _opt_id(institution_id),
            _opt_id(program_id),
            _opt_id(term_id),
            document_date,
            review_status,
            title,
            summary,
            artifact_link,
            json.dumps(source_metadata, ensure_ascii=False),
        )

    artifact = _row_to_dict(row)
    assert artifact is not None
    return artifact


@mcp.tool()
async def extract_artifact_to_draft(
    artifact_id: int,
    raw_text: str = "",
    parser_version: str = "heuristic_v1",
    confidence: float = 0.55,
) -> dict:
    """Create a draft extraction payload from an artifact's OCR text."""
    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        artifact_row = await conn.fetchrow("SELECT * FROM artifacts WHERE id = $1", artifact_id)
        if artifact_row is None:
            return {"error": f"Artifact {artifact_id} not found."}

        payload = _heuristic_extract(raw_text)
        payload["artifact_type"] = artifact_row["artifact_type"]
        payload["source_system"] = artifact_row["source_system"]

        row = await conn.fetchrow(
            "INSERT INTO artifact_extracts (artifact_id, parser_version, confidence, extraction_status, extracted_payload, raw_text) "
            "VALUES ($1, $2, $3, 'draft', $4::jsonb, NULLIF($5, '')) RETURNING *",
            artifact_id,
            parser_version,
            max(0.0, min(confidence, 1.0)),
            json.dumps(payload, ensure_ascii=False),
            raw_text,
        )

        await conn.execute(
            "UPDATE artifacts SET review_status = 'in_review', updated_at = NOW() WHERE id = $1",
            artifact_id,
        )

    result = _row_to_dict(row)
    assert result is not None
    return result


@mcp.tool()
async def review_extraction(
    artifact_extract_id: int,
    reviewer: str,
    decision: str,
    corrections: dict | None = None,
    review_notes: str = "",
) -> dict:
    """Accept/reject extraction drafts and persist review provenance."""
    if corrections is None:
        corrections = {}

    normalized = decision.strip().lower()
    if normalized not in {"accepted", "rejected", "needs_changes"}:
        return {"error": "decision must be one of: accepted, rejected, needs_changes"}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        extract_row = await conn.fetchrow(
            "SELECT * FROM artifact_extracts WHERE id = $1", artifact_extract_id
        )
        if extract_row is None:
            return {"error": f"artifact_extract {artifact_extract_id} not found."}

        review_row = await conn.fetchrow(
            "INSERT INTO artifact_reviews (artifact_extract_id, reviewer, decision, corrections, review_notes) "
            "VALUES ($1, $2, $3, $4::jsonb, NULLIF($5, '')) RETURNING *",
            artifact_extract_id,
            reviewer,
            normalized,
            json.dumps(corrections, ensure_ascii=False),
            review_notes,
        )

        extraction_status = {
            "accepted": "accepted",
            "rejected": "rejected",
            "needs_changes": "needs_changes",
        }[normalized]
        artifact_review_status = {
            "accepted": "reviewed",
            "rejected": "rejected",
            "needs_changes": "in_review",
        }[normalized]

        await conn.execute(
            "UPDATE artifact_extracts SET extraction_status = $1 WHERE id = $2",
            extraction_status,
            artifact_extract_id,
        )
        await conn.execute(
            "UPDATE artifacts SET review_status = $1, updated_at = NOW() WHERE id = $2",
            artifact_review_status,
            int(extract_row["artifact_id"]),
        )

    result = _row_to_dict(review_row)
    assert result is not None
    return result


@mcp.tool()
async def get_assessment_summary(
    learner_id: int,
    assessment_definition_code: str = "",
    limit: int = 25,
) -> dict:
    """Summarize assessment history and latest outcomes for a learner."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT ad.code, ad.name, ad.subject_area, ad.measure_type, ad.unit, "
        "ae.id AS assessment_event_id, ae.assessed_on, ae.term_id, ae.staff_contact_id, "
        "ar.result_numeric, ar.result_text, ar.result_boolean, ar.percentile, "
        "ar.proficiency_band, ar.normalized_score "
        "FROM assessment_events ae "
        "JOIN assessment_definitions ad ON ad.id = ae.assessment_definition_id "
        "LEFT JOIN assessment_results ar ON ar.assessment_event_id = ae.id "
        "WHERE ae.learner_id = $1"
    )
    params: list[Any] = [learner_id]

    if assessment_definition_code:
        params.append(assessment_definition_code)
        sql += f" AND ad.code = ${len(params)}"

    params.append(max(1, min(limit, 200)))
    sql += f" ORDER BY ae.assessed_on DESC, ae.id DESC LIMIT ${len(params)}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results = _rows_to_dicts(rows)
    by_definition: dict[str, dict] = {}
    for row in results:
        code = row["code"]
        entry = by_definition.setdefault(
            code,
            {
                "code": code,
                "name": row["name"],
                "subject_area": row["subject_area"],
                "measure_type": row["measure_type"],
                "count": 0,
                "latest_assessed_on": row["assessed_on"],
                "latest_result": None,
                "numeric_values": [],
            },
        )
        entry["count"] += 1
        if entry["latest_result"] is None:
            entry["latest_result"] = {
                "result_numeric": row["result_numeric"],
                "result_text": row["result_text"],
                "result_boolean": row["result_boolean"],
                "percentile": row["percentile"],
                "normalized_score": row["normalized_score"],
            }
        if row["result_numeric"] is not None:
            entry["numeric_values"].append(row["result_numeric"])

    for entry in by_definition.values():
        values = entry.pop("numeric_values")
        if values:
            entry["numeric_avg"] = round(sum(values) / len(values), 4)
            entry["numeric_min"] = min(values)
            entry["numeric_max"] = max(values)

    return {
        "learner_id": learner_id,
        "recent_results": results,
        "by_definition": list(by_definition.values()),
    }


@mcp.tool()
async def get_report_card_history(learner_id: int, subject: str = "") -> list[dict]:
    """Return structured report-card facts over time."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT rcf.*, t.label AS term_label "
        "FROM report_card_facts rcf "
        "LEFT JOIN terms t ON t.id = rcf.term_id "
        "WHERE rcf.learner_id = $1"
    )
    params: list[Any] = [learner_id]

    if subject:
        params.append(subject)
        sql += f" AND rcf.subject = ${len(params)}"

    sql += " ORDER BY COALESCE(rcf.issued_on, DATE '1900-01-01') DESC, rcf.id DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return _rows_to_dicts(rows)


@mcp.tool()
async def get_activity_performance_summary(
    learner_id: int,
    activity_code: str = "",
    metric_code: str = "",
    days: int = 180,
) -> dict:
    """Summarize metric observations for activities/program performance."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT mo.*, md.code AS metric_code, md.name AS metric_name, md.unit, md.polarity, md.measure_type, "
        "ad.code AS activity_code, ad.name AS activity_name "
        "FROM metric_observations mo "
        "JOIN metric_definitions md ON md.id = mo.metric_definition_id "
        "LEFT JOIN activity_definitions ad ON ad.id = md.activity_definition_id "
        "WHERE mo.learner_id = $1 AND mo.observed_at >= NOW() - ($2::int || ' days')::interval"
    )
    params: list[Any] = [learner_id, max(1, days)]

    if activity_code:
        params.append(activity_code)
        sql += f" AND ad.code = ${len(params)}"

    if metric_code:
        params.append(metric_code)
        sql += f" AND md.code = ${len(params)}"

    sql += " ORDER BY mo.observed_at DESC, mo.id DESC"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    observations = _rows_to_dicts(rows)
    metrics: dict[str, dict] = {}

    for obs in observations:
        key = f"{obs['activity_code']}::{obs['metric_code']}"
        bucket = metrics.setdefault(
            key,
            {
                "activity_code": obs["activity_code"],
                "activity_name": obs["activity_name"],
                "metric_code": obs["metric_code"],
                "metric_name": obs["metric_name"],
                "unit": obs["unit"],
                "polarity": obs["polarity"],
                "measure_type": obs["measure_type"],
                "count": 0,
                "latest": None,
                "numeric_values": [],
            },
        )
        bucket["count"] += 1
        if bucket["latest"] is None:
            bucket["latest"] = {
                "observed_at": obs["observed_at"],
                "value_numeric": obs["value_numeric"],
                "value_text": obs["value_text"],
                "value_boolean": obs["value_boolean"],
                "context": obs["context"],
            }
        if obs["value_numeric"] is not None:
            bucket["numeric_values"].append(obs["value_numeric"])

    for bucket in metrics.values():
        values = bucket.pop("numeric_values")
        if values:
            bucket["numeric_avg"] = round(sum(values) / len(values), 4)
            bucket["numeric_min"] = min(values)
            bucket["numeric_max"] = max(values)

    return {
        "learner_id": learner_id,
        "window_days": days,
        "metric_summaries": list(metrics.values()),
        "recent_observations": observations[:50],
    }


@mcp.tool()
async def record_metric_observation(
    learner_id: int,
    activity_code: str,
    metric_code: str,
    value_numeric: float | None = None,
    value_text: str = "",
    value_boolean: bool | None = None,
    observed_at: str = "",
    unit: str = "",
    polarity: str = "higher_is_better",
    measure_type: str = "numeric",
    context: dict | None = None,
    source_artifact_id: int = 0,
    recorded_by: str = "",
) -> dict:
    """Record a generic time-series performance observation."""
    if context is None:
        context = {}

    if polarity not in {"higher_is_better", "lower_is_better", "neutral"}:
        return {"error": "polarity must be one of: higher_is_better, lower_is_better, neutral"}

    if observed_at:
        try:
            observed_at = _normalize_datetime(observed_at, "observed_at")
        except ValueError as exc:
            return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        activity_row = await conn.fetchrow(
            "INSERT INTO activity_definitions (code, name, activity_type) "
            "VALUES ($1, $2, 'general') ON CONFLICT (code) DO UPDATE SET name = activity_definitions.name "
            "RETURNING id, code, name",
            activity_code,
            _title_from_code(activity_code),
        )
        assert activity_row is not None
        activity_id = int(activity_row["id"])

        metric_row = await conn.fetchrow(
            "INSERT INTO metric_definitions (activity_definition_id, code, name, unit, polarity, measure_type) "
            "VALUES ($1, $2, $3, NULLIF($4, ''), $5, $6) "
            "ON CONFLICT (activity_definition_id, code) DO UPDATE SET "
            "unit = COALESCE(metric_definitions.unit, EXCLUDED.unit), "
            "polarity = metric_definitions.polarity, "
            "measure_type = metric_definitions.measure_type "
            "RETURNING id, code, name",
            activity_id,
            metric_code,
            _title_from_code(metric_code),
            unit,
            polarity,
            measure_type,
        )
        assert metric_row is not None

        obs_row = await conn.fetchrow(
            "INSERT INTO metric_observations ("
            "learner_id, metric_definition_id, observed_at, value_numeric, value_text, value_boolean, "
            "context, source_artifact_id, recorded_by"
            ") VALUES ("
            "$1, $2, COALESCE(NULLIF($3, '')::timestamptz, NOW()), $4, NULLIF($5, ''), $6, $7::jsonb, $8, NULLIF($9, '')"
            ") RETURNING *",
            learner_id,
            int(metric_row["id"]),
            observed_at,
            value_numeric,
            value_text,
            value_boolean,
            json.dumps(context, ensure_ascii=False),
            _opt_id(source_artifact_id),
            recorded_by,
        )

    observation = _row_to_dict(obs_row)
    assert observation is not None
    observation["activity_code"] = activity_code
    observation["metric_code"] = metric_code
    return observation


@mcp.tool()
async def record_observation(
    learner_id: int,
    observation_text: str,
    domain: str = "",
    observed_on: str = "",
    source: str = "manual",
    source_artifact_id: int = 0,
    recorded_by: str = "",
) -> dict:
    """Record a narrative developmental/academic observation."""
    if observed_on:
        try:
            observed_on = _normalize_date(observed_on, "observed_on")
        except ValueError as exc:
            return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        row = await conn.fetchrow(
            "INSERT INTO observations ("
            "learner_id, observed_on, domain, source, observation_text, source_artifact_id, recorded_by"
            ") VALUES ("
            "$1, COALESCE(NULLIF($2, '')::date, CURRENT_DATE), NULLIF($3, ''), NULLIF($4, ''), $5, $6, NULLIF($7, '')"
            ") RETURNING *",
            learner_id,
            observed_on,
            domain,
            source,
            observation_text,
            _opt_id(source_artifact_id),
            recorded_by,
        )

    observation = _row_to_dict(row)
    assert observation is not None
    return observation


@mcp.tool()
async def upsert_goal(
    learner_id: int,
    title: str,
    description: str = "",
    goal_type: str = "",
    status: str = "open",
    target_date: str = "",
    success_criteria: dict | None = None,
    owner: str = "",
    goal_id: int = 0,
) -> dict:
    """Create or update learner goals and intervention targets."""
    if success_criteria is None:
        success_criteria = {}

    if target_date:
        try:
            target_date = _normalize_date(target_date, "target_date")
        except ValueError as exc:
            return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        if goal_id > 0:
            row = await conn.fetchrow(
                "UPDATE goals SET "
                "title = $1, description = NULLIF($2, ''), goal_type = NULLIF($3, ''), status = $4, "
                "target_date = NULLIF($5, '')::date, success_criteria = $6::jsonb, owner = NULLIF($7, ''), "
                "updated_at = NOW() "
                "WHERE id = $8 AND learner_id = $9 RETURNING *",
                title,
                description,
                goal_type,
                status,
                target_date,
                json.dumps(success_criteria, ensure_ascii=False),
                owner,
                goal_id,
                learner_id,
            )
            if row is None:
                return {"error": f"Goal {goal_id} not found for learner {learner_id}."}
        else:
            row = await conn.fetchrow(
                "INSERT INTO goals ("
                "learner_id, goal_type, title, description, status, target_date, success_criteria, owner"
                ") VALUES ("
                "$1, NULLIF($2, ''), $3, NULLIF($4, ''), $5, NULLIF($6, '')::date, $7::jsonb, NULLIF($8, '')"
                ") RETURNING *",
                learner_id,
                goal_type,
                title,
                description,
                status,
                target_date,
                json.dumps(success_criteria, ensure_ascii=False),
                owner,
            )

    goal = _row_to_dict(row)
    assert goal is not None
    return goal


@mcp.tool()
async def get_open_actions(
    learner_id: int = 0,
    include_completed: bool = False,
    limit: int = 50,
) -> list[dict]:
    """List outstanding intervention/action items."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT ai.*, l.display_name AS learner_name, g.title AS goal_title "
        "FROM action_items ai "
        "JOIN learners l ON l.id = ai.learner_id "
        "LEFT JOIN goals g ON g.id = ai.goal_id "
        "WHERE 1=1"
    )
    params: list[Any] = []

    if learner_id > 0:
        params.append(learner_id)
        sql += f" AND ai.learner_id = ${len(params)}"

    if not include_completed:
        sql += " AND ai.status <> 'completed'"

    params.append(max(1, min(limit, 200)))
    sql += f" ORDER BY COALESCE(ai.due_date, DATE '2999-12-31'), ai.id DESC LIMIT ${len(params)}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return _rows_to_dicts(rows)


@mcp.tool()
async def generate_term_brief(
    learner_id: int,
    term_id: int = 0,
    term_label: str = "",
) -> dict:
    """Generate a structured term brief with provenance context."""
    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        resolved_term_id = _opt_id(term_id)
        resolved_term = None
        if resolved_term_id is None and term_label:
            resolved_term = await conn.fetchrow("SELECT * FROM terms WHERE label = $1 ORDER BY id DESC LIMIT 1", term_label)
            if resolved_term is not None:
                resolved_term_id = int(resolved_term["id"])
        elif resolved_term_id is not None:
            resolved_term = await conn.fetchrow("SELECT * FROM terms WHERE id = $1", resolved_term_id)

        artifact_where = "WHERE learner_id = $1"
        artifact_params: list[Any] = [learner_id]
        if resolved_term_id is not None:
            artifact_params.append(resolved_term_id)
            artifact_where += f" AND term_id = ${len(artifact_params)}"

        artifact_stats = await conn.fetch(
            f"SELECT artifact_type, review_status, COUNT(*) AS count FROM artifacts {artifact_where} "
            "GROUP BY artifact_type, review_status ORDER BY artifact_type, review_status",
            *artifact_params,
        )

        report_cards = await conn.fetch(
            "SELECT subject, grade_mark, teacher_comment, issued_on "
            "FROM report_card_facts WHERE learner_id = $1 "
            + ("AND term_id = $2 " if resolved_term_id is not None else "")
            + "ORDER BY COALESCE(issued_on, DATE '1900-01-01') DESC, id DESC LIMIT 20",
            *([learner_id, resolved_term_id] if resolved_term_id is not None else [learner_id]),
        )

        assessments = await conn.fetch(
            "SELECT ad.code, ad.name, ae.assessed_on, ar.result_numeric, ar.result_text, ar.percentile "
            "FROM assessment_events ae "
            "JOIN assessment_definitions ad ON ad.id = ae.assessment_definition_id "
            "LEFT JOIN assessment_results ar ON ar.assessment_event_id = ae.id "
            "WHERE ae.learner_id = $1 "
            + ("AND ae.term_id = $2 " if resolved_term_id is not None else "")
            + "ORDER BY ae.assessed_on DESC, ae.id DESC LIMIT 25",
            *([learner_id, resolved_term_id] if resolved_term_id is not None else [learner_id]),
        )

        metric_recent = await conn.fetch(
            "SELECT ad.code AS activity_code, md.code AS metric_code, mo.value_numeric, mo.value_text, mo.observed_at "
            "FROM metric_observations mo "
            "JOIN metric_definitions md ON md.id = mo.metric_definition_id "
            "LEFT JOIN activity_definitions ad ON ad.id = md.activity_definition_id "
            "WHERE mo.learner_id = $1 ORDER BY mo.observed_at DESC LIMIT 25",
            learner_id,
        )

        goals = await conn.fetch(
            "SELECT id, title, status, target_date FROM goals WHERE learner_id = $1 "
            "ORDER BY (status = 'completed') ASC, COALESCE(target_date, DATE '2999-12-31'), id DESC LIMIT 25",
            learner_id,
        )

        observations = await conn.fetch(
            "SELECT observed_on, domain, observation_text, source FROM observations "
            "WHERE learner_id = $1 ORDER BY observed_on DESC, id DESC LIMIT 15",
            learner_id,
        )

    artifact_rows = _rows_to_dicts(artifact_stats)
    report_rows = _rows_to_dicts(report_cards)
    assessment_rows = _rows_to_dicts(assessments)
    metric_rows = _rows_to_dicts(metric_recent)
    goal_rows = _rows_to_dicts(goals)
    observation_rows = _rows_to_dicts(observations)

    total_artifacts = sum(int(row["count"]) for row in artifact_rows)
    open_goals = sum(1 for row in goal_rows if row["status"] in {"open", "in_progress"})

    summary_lines = [
        f"Learner: {learner['display_name']}",
        f"Artifacts in scope: {total_artifacts}",
        f"Recent assessments: {len(assessment_rows)}",
        f"Report-card facts: {len(report_rows)}",
        f"Open goals: {open_goals}",
        f"Recent observations: {len(observation_rows)}",
    ]

    return {
        "learner": learner,
        "term": _row_to_dict(resolved_term),
        "summary": " | ".join(summary_lines),
        "artifact_summary": artifact_rows,
        "report_card_facts": report_rows,
        "assessment_results": assessment_rows,
        "recent_metric_observations": metric_rows,
        "goals": goal_rows,
        "observations": observation_rows,
        "provenance": {
            "source_tables": [
                "artifacts",
                "report_card_facts",
                "assessment_events",
                "assessment_results",
                "metric_observations",
                "goals",
                "observations",
            ],
            "evidence_model": "artifact + extraction + review + canonical facts",
        },
    }


@mcp.tool()
async def recommend_activities_for_age(
    age_months: int,
    category: str = "",
    indoor_outdoor: str = "",
) -> list[dict]:
    """Recommend catalog activities by age and optional filters."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT * FROM activity_catalog WHERE min_age_months <= $1 AND max_age_months >= $1"
    )
    params: list[Any] = [age_months]

    if category:
        params.append(category)
        sql += f" AND category = ${len(params)}"

    if indoor_outdoor in {"indoor", "outdoor"}:
        params.append(indoor_outdoor)
        sql += f" AND (indoor_outdoor = ${len(params)} OR indoor_outdoor = 'both')"

    sql += " ORDER BY title"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return _rows_to_dicts(rows)


@mcp.tool()
async def create_weekly_activity_plan(
    learner_id: int,
    week_start: str,
    activities: list[dict],
    plan_type: str = "activity",
    notes: str = "",
) -> dict:
    """Create/replace normalized weekly activity plan and plan items."""
    try:
        week_start = _normalize_date(week_start, "week_start")
    except ValueError as exc:
        return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        learner = await _fetch_learner_or_none(conn, learner_id)
        if learner is None:
            return {"error": f"Learner {learner_id} not found."}

        async with conn.transaction():
            plan_row = await conn.fetchrow(
                "INSERT INTO weekly_plans (learner_id, week_start, plan_type, notes) "
                "VALUES ($1, $2::text::date, $3, NULLIF($4, '')) "
                "ON CONFLICT (learner_id, week_start, plan_type) DO UPDATE SET "
                "notes = EXCLUDED.notes, updated_at = NOW() "
                "RETURNING *",
                learner_id,
                week_start,
                plan_type,
                notes,
            )
            assert plan_row is not None
            plan_id = int(plan_row["id"])

            await conn.execute("DELETE FROM weekly_plan_items WHERE weekly_plan_id = $1", plan_id)

            inserted = 0
            for item in activities:
                day_of_week = str(item.get("day") or item.get("day_of_week") or "Unspecified")
                title = str(item.get("title") or "Activity")
                scheduled_time = str(item.get("time") or item.get("scheduled_time") or "")
                duration_minutes = item.get("duration_minutes")
                notes_value = str(item.get("notes") or "")
                status = str(item.get("status") or "planned")

                catalog_id = _opt_id(int(item.get("activity_catalog_id", 0) or 0))
                if catalog_id is None:
                    legacy_activity_id = _opt_id(int(item.get("activity_id", 0) or 0))
                    if legacy_activity_id is not None:
                        catalog_id = legacy_activity_id

                activity_definition_id = _opt_id(
                    int(item.get("activity_definition_id", 0) or 0)
                )

                if duration_minutes is None and notes_value:
                    match = re.search(r"(\d{1,3})\s*min", notes_value.lower())
                    if match:
                        duration_minutes = int(match.group(1))

                metadata = item.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}

                await conn.execute(
                    "INSERT INTO weekly_plan_items ("
                    "weekly_plan_id, day_of_week, activity_catalog_id, activity_definition_id, title, "
                    "scheduled_time, duration_minutes, notes, status, metadata"
                    ") VALUES ("
                    "$1, $2, $3, $4, $5, NULLIF($6, ''), $7, NULLIF($8, ''), NULLIF($9, ''), $10::jsonb"
                    ")",
                    plan_id,
                    day_of_week,
                    catalog_id,
                    activity_definition_id,
                    title,
                    scheduled_time,
                    duration_minutes,
                    notes_value,
                    status,
                    json.dumps(metadata, ensure_ascii=False),
                )
                inserted += 1

    return {
        "status": "created",
        "learner_id": learner_id,
        "week_start": week_start,
        "plan_type": plan_type,
        "activities_count": inserted,
    }


@mcp.tool()
async def get_weekly_activity_plan(
    learner_id: int,
    week_start: str = "",
    plan_type: str = "activity",
) -> dict:
    """Fetch weekly activity plan and normalized plan items."""
    if not week_start:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.strftime("%Y-%m-%d")
    else:
        try:
            week_start = _normalize_date(week_start, "week_start")
        except ValueError as exc:
            return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        plan = await conn.fetchrow(
            "SELECT * FROM weekly_plans WHERE learner_id = $1 AND week_start = $2::text::date AND plan_type = $3",
            learner_id,
            week_start,
            plan_type,
        )
        if plan is None:
            return {
                "learner_id": learner_id,
                "week_start": week_start,
                "plan_type": plan_type,
                "plan": [],
                "message": "No plan found for this week.",
            }

        items = await conn.fetch(
            "SELECT wpi.*, ac.title AS catalog_title, ad.code AS activity_code "
            "FROM weekly_plan_items wpi "
            "LEFT JOIN activity_catalog ac ON ac.id = wpi.activity_catalog_id "
            "LEFT JOIN activity_definitions ad ON ad.id = wpi.activity_definition_id "
            "WHERE wpi.weekly_plan_id = $1 ORDER BY wpi.day_of_week, wpi.id",
            int(plan["id"]),
        )

    result = _row_to_dict(plan)
    assert result is not None
    result["plan"] = _rows_to_dicts(items)
    return result


# ---------------------------------------------------------------------------
# Compatibility tools (legacy family-edu interface)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_children() -> list[dict]:
    """Legacy alias for list_learners()."""
    learners = await list_learners()
    for learner in learners:
        learner["name"] = learner.pop("display_name")
        learner["dob"] = learner.pop("date_of_birth")
    return learners


@mcp.tool()
async def add_child(name: str, date_of_birth: str) -> dict:
    """Legacy alias for create_learner()."""
    learner = await create_learner(name, date_of_birth)
    if "error" in learner:
        return learner
    learner["name"] = learner.pop("display_name")
    learner["dob"] = learner.pop("date_of_birth")
    return learner


@mcp.tool()
async def get_milestones(child_id: int, category: str = "") -> list[dict]:
    """Legacy milestone listing backed by definition + status model."""
    await _ensure_initialized()
    pool = await _get_pool()

    sql = (
        "SELECT lms.id, lms.learner_id AS child_id, md.id AS milestone_definition_id, "
        "md.category, md.description, md.expected_age_months, lms.achieved_date, lms.status, lms.notes "
        "FROM learner_milestone_status lms "
        "JOIN milestone_definitions md ON md.id = lms.milestone_definition_id "
        "WHERE lms.learner_id = $1"
    )
    params: list[Any] = [child_id]

    if category:
        params.append(category)
        sql += f" AND md.category = ${len(params)}"

    sql += " ORDER BY md.expected_age_months, md.id"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    milestones = _rows_to_dicts(rows)
    for milestone in milestones:
        milestone["achieved"] = milestone["status"] == "achieved"
    return milestones


@mcp.tool()
async def record_milestone(
    child_id: int, milestone_id: int, achieved_date: str = ""
) -> dict:
    """Legacy milestone update; milestone_id refers to learner_milestone_status.id."""
    if not achieved_date:
        achieved_date = datetime.now().strftime("%Y-%m-%d")

    try:
        achieved_date = _normalize_date(achieved_date, "achieved_date")
    except ValueError as exc:
        return {"error": str(exc)}

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE learner_milestone_status SET status = 'achieved', achieved_date = $1::text::date, updated_at = NOW() "
            "WHERE id = $2 AND learner_id = $3 RETURNING *",
            achieved_date,
            milestone_id,
            child_id,
        )

    if row is None:
        return {"error": f"Milestone {milestone_id} not found for child {child_id}."}

    payload = _row_to_dict(row)
    assert payload is not None
    payload["achieved"] = True
    return payload


@mcp.tool()
async def get_activities_for_age(
    age_months: int, category: str = "", indoor_outdoor: str = ""
) -> list[dict]:
    """Legacy alias for recommend_activities_for_age()."""
    return await recommend_activities_for_age(age_months, category, indoor_outdoor)


@mcp.tool()
async def create_weekly_plan(
    child_id: int, week_start: str, activities: list[dict]
) -> dict:
    """Legacy alias for create_weekly_activity_plan()."""
    result = await create_weekly_activity_plan(child_id, week_start, activities)
    if "learner_id" in result:
        result["child_id"] = result.pop("learner_id")
    return result


@mcp.tool()
async def get_weekly_plan(child_id: int, week_start: str = "") -> dict:
    """Legacy alias for get_weekly_activity_plan()."""
    plan = await get_weekly_activity_plan(child_id, week_start)
    if "learner_id" in plan:
        plan["child_id"] = plan.pop("learner_id")
    return plan


@mcp.tool()
async def add_journal_entry(
    child_id: int, notes: str, milestones_achieved: list[int] | None = None
) -> dict:
    """Legacy journal entry tool mapped to normalized journal + milestone status."""
    if milestones_achieved is None:
        milestones_achieved = []

    today = datetime.now().strftime("%Y-%m-%d")

    await _ensure_initialized()
    pool = await _get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            if milestones_achieved:
                await conn.execute(
                    "UPDATE learner_milestone_status SET status = 'achieved', achieved_date = $1::text::date, updated_at = NOW() "
                    "WHERE learner_id = $2 AND id = ANY($3::bigint[])",
                    today,
                    child_id,
                    milestones_achieved,
                )

            row = await conn.fetchrow(
                "INSERT INTO journal_entries (learner_id, entry_date, entry_text) "
                "VALUES ($1, $2::text::date, $3) RETURNING *",
                child_id,
                today,
                notes,
            )

    entry = _row_to_dict(row)
    assert entry is not None
    return {
        "id": entry["id"],
        "child_id": child_id,
        "date": today,
        "notes": notes,
        "milestones_achieved": milestones_achieved,
    }


if __name__ == "__main__":
    asyncio.run(_ensure_initialized())
    mcp.run()
