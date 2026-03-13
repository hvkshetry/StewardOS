"""Activity recommendation and weekly planning tools."""

import json
import re
from datetime import datetime, timedelta
from typing import Any

from helpers import (
    _fetch_learner_or_none,
    _normalize_date,
    _opt_id,
    _row_to_dict,
    _rows_to_dicts,
)


def register_planning_tools(mcp, get_pool):

    @mcp.tool()
    async def recommend_activities_for_age(
        age_months: int,
        category: str = "",
        indoor_outdoor: str = "",
    ) -> list[dict]:
        """Recommend catalog activities by age and optional filters."""
        pool = await get_pool()

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

        pool = await get_pool()

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

        pool = await get_pool()

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
