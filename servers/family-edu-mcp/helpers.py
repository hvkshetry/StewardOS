"""Shared helper functions for family-edu-mcp domain modules."""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import asyncpg


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


async def _fetch_learner_or_none(conn: asyncpg.Connection, learner_id: int) -> dict | None:
    row = await conn.fetchrow("SELECT * FROM learners WHERE id = $1", learner_id)
    return _row_to_dict(row)
