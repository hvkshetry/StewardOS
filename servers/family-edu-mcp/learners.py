"""Learner profile management and enrollment tools."""

import json
from typing import Any

from helpers import (
    _child_age_months,
    _fetch_learner_or_none,
    _normalize_date,
    _row_to_dict,
    _rows_to_dicts,
)


def register_learner_tools(mcp, get_pool):

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

        pool = await get_pool()

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

        learner["age_months"] = _child_age_months(learner["date_of_birth"])
        return learner

    @mcp.tool()
    async def list_learners() -> list[dict]:
        """List all learners with current age in months."""
        pool = await get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM learners ORDER BY display_name")

        learners = _rows_to_dicts(rows)
        for learner in learners:
            learner["age_months"] = _child_age_months(learner["date_of_birth"])
        return learners

    @mcp.tool()
    async def get_learner_profile(learner_id: int) -> dict:
        """Return learner profile, milestone status summary, and active context."""
        pool = await get_pool()

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
        pool = await get_pool()

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

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return _rows_to_dicts(rows)
