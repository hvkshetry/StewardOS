"""One-time migration from legacy SQLite family_edu.db into normalized Postgres schema."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import asyncpg

from seed_data import activity_key, milestone_code

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://family_edu:changeme@localhost:5434/family_edu"
)
SQLITE_DB_PATH = os.environ.get("FAMILY_EDU_DB", "./family_edu.db")
SCHEMA_SQL = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")


def _read_legacy_sqlite(db_path: str) -> dict[str, list[dict]]:
    uri = f"file:{db_path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        payload: dict[str, list[dict]] = {}
        for table in [
            "children",
            "milestones",
            "activities",
            "weekly_plans",
            "progress_journal",
        ]:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            payload[table] = [dict(row) for row in rows]
        return payload
    finally:
        conn.close()


def _safe_json(value: Any, default: Any) -> str:
    if value is None:
        return json.dumps(default, ensure_ascii=False)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return json.dumps(default, ensure_ascii=False)
        try:
            parsed = json.loads(stripped)
            return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            return json.dumps(default, ensure_ascii=False)
    return json.dumps(default, ensure_ascii=False)


def _parse_duration_minutes(item: dict) -> int | None:
    if isinstance(item.get("duration_minutes"), int):
        return int(item["duration_minutes"])
    notes = str(item.get("notes") or "")
    for token in notes.split():
        if token.isdigit():
            return int(token)
    return None


async def _set_sequence(conn: asyncpg.Connection, table: str) -> None:
    await conn.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table}), 1),
            EXISTS(SELECT 1 FROM {table})
        )
        """
    )


async def _migrate(legacy: dict[str, list[dict]]) -> None:
    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=2,
        server_settings={"search_path": "family_edu,public"},
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(SCHEMA_SQL)

                await conn.execute(
                    "TRUNCATE TABLE "
                    "comments, comment_threads, journal_entries, observations, weekly_plan_items, weekly_plans, "
                    "action_items, goal_progress, goals, awards_or_certificates, rubric_scores, rubric_definitions, "
                    "metric_observations, metric_definitions, activity_sessions, seasons, activity_definitions, "
                    "support_plans, attendance_facts, report_card_facts, assessment_results, assessment_events, "
                    "assessment_definitions, artifact_reviews, artifact_extracts, artifact_links, artifacts, "
                    "learner_milestone_status, milestone_definitions, activity_catalog, enrollments, staff_contacts, "
                    "terms, academic_years, programs, institutions, guardian_relationships, learners "
                    "RESTART IDENTITY CASCADE"
                )

                # Learners
                for row in legacy["children"]:
                    await conn.execute(
                        "INSERT INTO learners (id, display_name, date_of_birth, metadata) "
                        "VALUES ($1, $2, $3::text::date, '{}'::jsonb)",
                        int(row["id"]),
                        row["name"],
                        row["dob"],
                    )

                # Milestone definitions + statuses
                definition_id_by_code: dict[str, int] = {}
                for row in legacy["milestones"]:
                    code = milestone_code(row["category"], row["description"])
                    def_row = await conn.fetchrow(
                        "INSERT INTO milestone_definitions (code, category, description, expected_age_months) "
                        "VALUES ($1, $2, $3, $4) "
                        "ON CONFLICT (code) DO UPDATE SET expected_age_months = EXCLUDED.expected_age_months "
                        "RETURNING id",
                        code,
                        row["category"],
                        row["description"],
                        row["expected_age_months"],
                    )
                    definition_id_by_code[code] = int(def_row["id"])

                status_id_by_old_milestone: dict[int, int] = {}
                for row in legacy["milestones"]:
                    code = milestone_code(row["category"], row["description"])
                    definition_id = definition_id_by_code[code]
                    status = "achieved" if row["achieved_date"] else "pending"
                    status_row = await conn.fetchrow(
                        "INSERT INTO learner_milestone_status ("
                        "learner_id, milestone_definition_id, status, achieved_date, notes"
                        ") VALUES ("
                        "$1, $2, $3, $4::text::date, ''"
                        ") ON CONFLICT (learner_id, milestone_definition_id) DO UPDATE SET "
                        "status = EXCLUDED.status, "
                        "achieved_date = COALESCE(learner_milestone_status.achieved_date, EXCLUDED.achieved_date), "
                        "updated_at = NOW() RETURNING id",
                        int(row["child_id"]),
                        definition_id,
                        status,
                        row["achieved_date"],
                    )
                    status_id_by_old_milestone[int(row["id"])] = int(status_row["id"])

                # Activity catalog
                for row in legacy["activities"]:
                    await conn.execute(
                        "INSERT INTO activity_catalog ("
                        "id, builtin_key, title, description, min_age_months, max_age_months, category, duration_minutes, indoor_outdoor"
                        ") VALUES ("
                        "$1, $2, $3, $4, $5, $6, $7, $8, $9"
                        ") ON CONFLICT (id) DO NOTHING",
                        int(row["id"]),
                        activity_key(row["title"]),
                        row["title"],
                        row["description"],
                        int(row["min_age_months"]),
                        int(row["max_age_months"]),
                        row["category"],
                        int(row["duration_minutes"]),
                        row["indoor_outdoor"],
                    )

                # Weekly plans and normalized items
                for row in legacy["weekly_plans"]:
                    plan_row = await conn.fetchrow(
                        "INSERT INTO weekly_plans (id, learner_id, week_start, plan_type, notes) "
                        "VALUES ($1, $2, $3::text::date, 'activity', '') RETURNING id",
                        int(row["id"]),
                        int(row["child_id"]),
                        row["week_start"],
                    )
                    plan_id = int(plan_row["id"])

                    try:
                        items = json.loads(row["plan_json"] or "[]")
                    except json.JSONDecodeError:
                        items = []

                    if isinstance(items, list):
                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            day = str(item.get("day") or item.get("day_of_week") or "Unspecified")
                            title = str(item.get("title") or "Activity")
                            sched = str(item.get("time") or item.get("scheduled_time") or "")
                            notes = str(item.get("notes") or "")
                            duration = _parse_duration_minutes(item)
                            activity_catalog_id = item.get("activity_id")
                            try:
                                activity_catalog_id = int(activity_catalog_id)
                            except Exception:
                                activity_catalog_id = None

                            await conn.execute(
                                "INSERT INTO weekly_plan_items ("
                                "weekly_plan_id, day_of_week, activity_catalog_id, title, scheduled_time, duration_minutes, notes, status, metadata"
                                ") VALUES ("
                                "$1, $2, $3, $4, NULLIF($5, ''), $6, NULLIF($7, ''), 'planned', '{}'::jsonb"
                                ")",
                                plan_id,
                                day,
                                activity_catalog_id,
                                title,
                                sched,
                                duration,
                                notes,
                            )

                # Journal entries + milestone status updates from journal references
                for row in legacy["progress_journal"]:
                    await conn.execute(
                        "INSERT INTO journal_entries (id, learner_id, entry_date, title, entry_text) "
                        "VALUES ($1, $2, $3::text::date, NULL, $4)",
                        int(row["id"]),
                        int(row["child_id"]),
                        row["date"],
                        row["notes"],
                    )

                    refs = json.loads(_safe_json(row.get("milestones_achieved"), []))
                    if isinstance(refs, list):
                        target_ids: list[int] = []
                        for ref in refs:
                            try:
                                legacy_mid = int(ref)
                            except Exception:
                                continue
                            mapped = status_id_by_old_milestone.get(legacy_mid)
                            if mapped is not None:
                                target_ids.append(mapped)

                        if target_ids:
                            await conn.execute(
                                "UPDATE learner_milestone_status SET "
                                "status = 'achieved', achieved_date = COALESCE(achieved_date, $1::text::date), updated_at = NOW() "
                                "WHERE id = ANY($2::bigint[]) AND learner_id = $3",
                                row["date"],
                                target_ids,
                                int(row["child_id"]),
                            )

                # Reset sequences for imported-id tables.
                for table in [
                    "learners",
                    "milestone_definitions",
                    "learner_milestone_status",
                    "activity_catalog",
                    "weekly_plans",
                    "weekly_plan_items",
                    "journal_entries",
                ]:
                    await _set_sequence(conn, table)

                checks = {
                    "learners": len(legacy["children"]),
                    "activity_catalog": len(legacy["activities"]),
                    "weekly_plans": len(legacy["weekly_plans"]),
                    "journal_entries": len(legacy["progress_journal"]),
                }

                print("Legacy SQLite -> Postgres migration completed.")
                for table, source_count in checks.items():
                    target_count = int(await conn.fetchval(f"SELECT COUNT(*) FROM {table}"))
                    print(f"{table}: source={source_count}, target={target_count}")

    finally:
        await pool.close()


def main() -> None:
    legacy = _read_legacy_sqlite(SQLITE_DB_PATH)
    print(f"Loaded legacy SQLite from {SQLITE_DB_PATH}")
    for table, rows in legacy.items():
        print(f"{table}: {len(rows)} rows")
    asyncio.run(_migrate(legacy))


if __name__ == "__main__":
    main()
