"""MCP server for child education and activity planning with SQLite backend."""

import json
import os
import sqlite3
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP
from seed_data import seed_activities, seed_milestones

DB_PATH = os.environ.get("FAMILY_EDU_DB", "./family_edu.db")

mcp = FastMCP(
    "family-edu-mcp",
    instructions=(
        "Child education and development tracking server. Track children's milestones, "
        "plan age-appropriate activities, create weekly plans, and maintain a progress "
        "journal. Backed by SQLite for persistent storage."
    ),
)


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    """Create tables if they do not exist."""
    conn = _get_db()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS children (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                dob TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                expected_age_months INTEGER,
                achieved_date TEXT,
                FOREIGN KEY (child_id) REFERENCES children(id)
            );

            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                min_age_months INTEGER NOT NULL DEFAULT 0,
                max_age_months INTEGER NOT NULL DEFAULT 216,
                category TEXT NOT NULL DEFAULT 'general',
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                indoor_outdoor TEXT NOT NULL DEFAULT 'both'
            );

            CREATE TABLE IF NOT EXISTS weekly_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                FOREIGN KEY (child_id) REFERENCES children(id),
                UNIQUE(child_id, week_start)
            );

            CREATE TABLE IF NOT EXISTS progress_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                notes TEXT NOT NULL,
                milestones_achieved TEXT DEFAULT '[]',
                FOREIGN KEY (child_id) REFERENCES children(id)
            );
        """)
        # Ensure reference catalogs exist without requiring a separate seed command.
        seed_activities(conn)
        child_rows = conn.execute("SELECT id FROM children").fetchall()
        for row in child_rows:
            seed_milestones(conn, row["id"])
        conn.commit()
    finally:
        conn.close()


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def _child_age_months(dob_str: str) -> int:
    """Calculate age in months from date of birth string."""
    dob = datetime.strptime(dob_str, "%Y-%m-%d")
    today = datetime.now()
    return (today.year - dob.year) * 12 + (today.month - dob.month)


@mcp.tool()
async def get_children() -> list[dict]:
    """List all registered children with their age in months."""
    conn = _get_db()
    try:
        rows = conn.execute("SELECT * FROM children ORDER BY name").fetchall()
        children = _rows_to_dicts(rows)
        for child in children:
            child["age_months"] = _child_age_months(child["dob"])
        return children
    finally:
        conn.close()


@mcp.tool()
async def add_child(name: str, date_of_birth: str) -> dict:
    """Add a child to track.

    Args:
        name: Child's name
        date_of_birth: Date of birth in YYYY-MM-DD format
    """
    try:
        datetime.strptime(date_of_birth, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO children (name, dob) VALUES (?, ?)",
            (name, date_of_birth),
        )
        child_id = int(cursor.lastrowid)
        # Seed milestones immediately so milestone tools work for new children.
        seed_milestones(conn, child_id)
        conn.commit()
        return {
            "id": child_id,
            "name": name,
            "dob": date_of_birth,
            "age_months": _child_age_months(date_of_birth),
        }
    finally:
        conn.close()


@mcp.tool()
async def get_milestones(child_id: int, category: str = "") -> list[dict]:
    """Get milestones for a child, optionally filtered by category.

    Args:
        child_id: ID of the child
        category: Optional category filter (e.g., 'motor', 'language', 'social', 'cognitive')
    """
    conn = _get_db()
    try:
        if category:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE child_id = ? AND category = ? "
                "ORDER BY expected_age_months",
                (child_id, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM milestones WHERE child_id = ? "
                "ORDER BY expected_age_months",
                (child_id,),
            ).fetchall()
        milestones = _rows_to_dicts(rows)
        for m in milestones:
            m["achieved"] = m["achieved_date"] is not None
        return milestones
    finally:
        conn.close()


@mcp.tool()
async def record_milestone(
    child_id: int, milestone_id: int, achieved_date: str = ""
) -> dict:
    """Mark a milestone as achieved for a child.

    Args:
        child_id: ID of the child
        milestone_id: ID of the milestone to mark
        achieved_date: Date achieved in YYYY-MM-DD format (defaults to today)
    """
    if not achieved_date:
        achieved_date = datetime.now().strftime("%Y-%m-%d")

    try:
        datetime.strptime(achieved_date, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    conn = _get_db()
    try:
        # Verify the milestone belongs to this child
        row = conn.execute(
            "SELECT * FROM milestones WHERE id = ? AND child_id = ?",
            (milestone_id, child_id),
        ).fetchone()
        if not row:
            return {"error": f"Milestone {milestone_id} not found for child {child_id}."}

        conn.execute(
            "UPDATE milestones SET achieved_date = ? WHERE id = ?",
            (achieved_date, milestone_id),
        )
        conn.commit()
        result = dict(row)
        result["achieved_date"] = achieved_date
        result["achieved"] = True
        return result
    finally:
        conn.close()


@mcp.tool()
async def get_activities_for_age(
    age_months: int, category: str = "", indoor_outdoor: str = ""
) -> list[dict]:
    """Get age-appropriate activities, optionally filtered.

    Args:
        age_months: Child's age in months
        category: Optional category filter (e.g., 'sensory', 'motor', 'language', 'art', 'music', 'science')
        indoor_outdoor: Optional filter: 'indoor', 'outdoor', or 'both'
    """
    conn = _get_db()
    try:
        query = (
            "SELECT * FROM activities WHERE min_age_months <= ? AND max_age_months >= ?"
        )
        params: list = [age_months, age_months]

        if category:
            query += " AND category = ?"
            params.append(category)

        if indoor_outdoor and indoor_outdoor in ("indoor", "outdoor"):
            query += " AND (indoor_outdoor = ? OR indoor_outdoor = 'both')"
            params.append(indoor_outdoor)

        query += " ORDER BY title"
        rows = conn.execute(query, params).fetchall()
        return _rows_to_dicts(rows)
    finally:
        conn.close()


@mcp.tool()
async def create_weekly_plan(
    child_id: int, week_start: str, activities: list[dict]
) -> dict:
    """Create or replace a weekly activity plan for a child.

    Args:
        child_id: ID of the child
        week_start: Monday of the plan week in YYYY-MM-DD format
        activities: List of activity dicts, each with keys like 'day', 'activity_id', 'title', 'time', 'notes'
    """
    try:
        datetime.strptime(week_start, "%Y-%m-%d")
    except ValueError:
        return {"error": "Invalid date format. Use YYYY-MM-DD."}

    conn = _get_db()
    try:
        plan_json = json.dumps(activities, ensure_ascii=False)
        conn.execute(
            "INSERT INTO weekly_plans (child_id, week_start, plan_json) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(child_id, week_start) DO UPDATE SET plan_json = excluded.plan_json",
            (child_id, week_start, plan_json),
        )
        conn.commit()
        return {
            "status": "created",
            "child_id": child_id,
            "week_start": week_start,
            "activities_count": len(activities),
        }
    finally:
        conn.close()


@mcp.tool()
async def get_weekly_plan(child_id: int, week_start: str = "") -> dict:
    """Get the weekly plan for a child. Defaults to current week if no date given.

    Args:
        child_id: ID of the child
        week_start: Optional Monday date in YYYY-MM-DD format (defaults to current week's Monday)
    """
    if not week_start:
        today = datetime.now()
        monday = today - timedelta(days=today.weekday())
        week_start = monday.strftime("%Y-%m-%d")

    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM weekly_plans WHERE child_id = ? AND week_start = ?",
            (child_id, week_start),
        ).fetchone()
        if not row:
            return {
                "child_id": child_id,
                "week_start": week_start,
                "plan": [],
                "message": "No plan found for this week.",
            }
        result = dict(row)
        result["plan"] = json.loads(result.pop("plan_json"))
        return result
    finally:
        conn.close()


@mcp.tool()
async def add_journal_entry(
    child_id: int, notes: str, milestones_achieved: list[int] | None = None
) -> dict:
    """Add a progress journal entry for a child.

    Args:
        child_id: ID of the child
        notes: Free-text progress notes
        milestones_achieved: Optional list of milestone IDs achieved today
    """
    if milestones_achieved is None:
        milestones_achieved = []

    today = datetime.now().strftime("%Y-%m-%d")

    conn = _get_db()
    try:
        # Mark any referenced milestones as achieved
        for mid in milestones_achieved:
            conn.execute(
                "UPDATE milestones SET achieved_date = ? WHERE id = ? AND child_id = ? AND achieved_date IS NULL",
                (today, mid, child_id),
            )

        cursor = conn.execute(
            "INSERT INTO progress_journal (child_id, date, notes, milestones_achieved) "
            "VALUES (?, ?, ?, ?)",
            (child_id, today, notes, json.dumps(milestones_achieved)),
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "child_id": child_id,
            "date": today,
            "notes": notes,
            "milestones_achieved": milestones_achieved,
        }
    finally:
        conn.close()


# Initialize the database on import
_init_db()

if __name__ == "__main__":
    mcp.run()
