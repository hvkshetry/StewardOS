"""MCP server for wger workout and nutrition tracking."""

import os
from datetime import date, timedelta

import httpx
from mcp.server.fastmcp import FastMCP

WGER_URL = os.environ.get("WGER_URL", "http://localhost:8280")
WGER_API_TOKEN = os.environ.get("WGER_API_TOKEN", "")

mcp = FastMCP(
    "wger-mcp",
    instructions=(
        "wger workout and nutrition tracking server. Provides tools to view "
        "workout routines, log exercises, track body weight and measurements, "
        "and manage nutrition plans. Uses the wger REST API v2."
    ),
)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Token {WGER_API_TOKEN}",
    }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=WGER_URL,
        headers=_headers(),
        timeout=30.0,
    )


async def _get(path: str, params: dict | None = None) -> dict | list | str:
    """Execute a GET request against the wger API."""
    try:
        async with _client() as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


async def _post(path: str, payload: dict) -> dict | str:
    """Execute a POST request against the wger API."""
    try:
        async with _client() as client:
            resp = await client.post(path, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


@mcp.tool()
async def get_routines() -> dict | list | str:
    """List workout routines with exercises and configurations."""
    return await _get("/api/v2/routine/", params={"format": "json"})


@mcp.tool()
async def get_workout_sessions(limit: int = 10) -> dict | list | str:
    """Get recent workout sessions with dates and notes."""
    return await _get(
        "/api/v2/workoutsession/",
        params={"format": "json", "limit": limit, "ordering": "-date"},
    )


@mcp.tool()
async def get_workout_log(days: int = 7) -> dict | list | str:
    """Get exercise log entries (sets, reps, weight) for the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    return await _get(
        "/api/v2/workoutlog/",
        params={"format": "json", "ordering": "-date", "date__gte": since},
    )


@mcp.tool()
async def get_nutrition_plan() -> dict | list | str:
    """Get current nutrition plan with macros and meal items."""
    return await _get("/api/v2/nutritionplan/", params={"format": "json"})


@mcp.tool()
async def get_body_weight(limit: int = 30) -> dict | list | str:
    """Get body weight entries over time (most recent first)."""
    return await _get(
        "/api/v2/weightentry/",
        params={"format": "json", "limit": limit, "ordering": "-date"},
    )


@mcp.tool()
async def get_body_measurements(limit: int = 30) -> dict | list | str:
    """Get body measurements (chest, waist, arms, etc.) over time."""
    return await _get(
        "/api/v2/measurement/",
        params={"format": "json", "limit": limit, "ordering": "-date"},
    )


@mcp.tool()
async def log_workout(
    exercise_id: int,
    reps: int,
    weight: float,
    workout_id: int,
    sets: int = 1,
) -> dict | str:
    """Log a workout entry. Specify exercise_id, reps, weight (kg), and workout_id.

    Creates `sets` number of identical log entries (default 1).
    """
    results = []
    for _ in range(sets):
        result = await _post(
            "/api/v2/workoutlog/",
            {
                "exercise": exercise_id,
                "reps": reps,
                "weight": str(weight),
                "workout": workout_id,
            },
        )
        results.append(result)
    return results if len(results) > 1 else results[0]


@mcp.tool()
async def log_weight(weight_kg: float, date_str: str = "") -> dict | str:
    """Add a body weight entry. date_str format: YYYY-MM-DD (default: today)."""
    payload: dict = {"weight": str(weight_kg)}
    if date_str:
        payload["date"] = date_str
    else:
        payload["date"] = date.today().isoformat()
    return await _post("/api/v2/weightentry/", payload)


@mcp.tool()
async def get_nutrition_plan_detail(plan_id: int) -> dict | list | str:
    """Get detailed nutrition plan with all meals and items.

    Args:
        plan_id: Nutrition plan ID
    """
    return await _get(f"/api/v2/nutritionplaninfo/{plan_id}/", params={"format": "json"})


@mcp.tool()
async def get_nutrition_values(plan_id: int) -> dict | list | str:
    """Get calculated nutritional values (calories, protein, carbs, fat) for a plan.

    Args:
        plan_id: Nutrition plan ID
    """
    return await _get(
        f"/api/v2/nutritionplan/{plan_id}/nutritional_values/",
        params={"format": "json"},
    )


@mcp.tool()
async def log_nutrition_diary(
    plan_id: int,
    ingredient_id: int,
    amount: float,
    meal_id: int | None = None,
) -> dict | str:
    """Log a food item to the nutrition diary.

    Args:
        plan_id: Nutrition plan ID
        ingredient_id: Ingredient/food ID from wger database
        amount: Amount in grams
        meal_id: Optional meal ID to associate with
    """
    payload: dict = {
        "plan": plan_id,
        "ingredient": ingredient_id,
        "amount": str(amount),
    }
    if meal_id is not None:
        payload["meal"] = meal_id
    return await _post("/api/v2/nutritiondiary/", payload)


@mcp.tool()
async def get_nutrition_diary(days: int = 7) -> dict | list | str:
    """Get nutrition diary entries for the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    return await _get(
        "/api/v2/nutritiondiary/",
        params={"format": "json", "ordering": "-datetime", "datetime__gte": since},
    )


@mcp.tool()
async def search_ingredients(query: str, language: int = 2) -> dict | list | str:
    """Search for food ingredients by name.

    Args:
        query: Search term (food name)
        language: Language ID (2 = English)
    """
    return await _get(
        "/api/v2/ingredient/search/",
        params={"format": "json", "term": query, "language": language},
    )


@mcp.tool()
async def log_body_measurement(
    category_id: int,
    value: float,
    date_str: str = "",
) -> dict | str:
    """Log a body measurement (e.g., waist circumference, arm size).

    Args:
        category_id: Measurement category ID (use get_measurement_categories to find)
        value: Measurement value
        date_str: Date in YYYY-MM-DD format (default: today)
    """
    payload: dict = {
        "category": category_id,
        "value": str(value),
        "date": date_str or date.today().isoformat(),
    }
    return await _post("/api/v2/measurement/", payload)


@mcp.tool()
async def get_measurement_categories() -> dict | list | str:
    """Get all body measurement categories (e.g., chest, waist, biceps)."""
    return await _get("/api/v2/measurement-category/", params={"format": "json"})


@mcp.tool()
async def get_user_profile() -> dict | list | str:
    """Get current user profile with personal settings and preferences."""
    return await _get("/api/v2/userprofile/", params={"format": "json"})


if __name__ == "__main__":
    mcp.run()
