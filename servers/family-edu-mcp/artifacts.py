"""Evidence artifact management, extraction, and review tools."""

import json
from typing import Any

from helpers import (
    _fetch_learner_or_none,
    _heuristic_extract,
    _normalize_date,
    _opt_id,
    _row_to_dict,
    _rows_to_dicts,
)


def register_artifact_tools(mcp, get_pool):

    @mcp.tool()
    async def search_artifacts(
        learner_id: int = 0,
        query: str = "",
        artifact_type: str = "",
        review_status: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """Search linked evidence artifacts and metadata."""
        pool = await get_pool()

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

        pool = await get_pool()

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
        pool = await get_pool()

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

        pool = await get_pool()

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
