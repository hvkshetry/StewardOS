"""Goal management and action item tools."""

import json
from typing import Any

from helpers import (
    _fetch_learner_or_none,
    _normalize_date,
    _row_to_dict,
    _rows_to_dicts,
)


def register_goal_tools(mcp, get_pool):

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

        pool = await get_pool()

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
        pool = await get_pool()

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
