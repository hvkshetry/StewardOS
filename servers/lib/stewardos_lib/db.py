"""Database utilities shared across MCP servers."""

import json
import uuid as uuid_mod
from datetime import date, datetime
from decimal import Decimal

import asyncpg


async def create_server_pool(
    database_url: str,
    *,
    schema: str = "public",
    min_size: int = 1,
    max_size: int = 5,
) -> asyncpg.Pool:
    """Create a connection pool with standardized settings."""
    return await asyncpg.create_pool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        server_settings={"search_path": f"{schema},public"},
    )


def row_to_dict(row: asyncpg.Record) -> dict:
    """Convert asyncpg Record to JSON-safe dict.

    Handles: date/datetime -> isoformat, Decimal -> float, UUID -> str,
    and JSON-like strings -> parsed dicts/lists.
    """
    d = {}
    for k, v in dict(row).items():
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
        elif isinstance(v, uuid_mod.UUID):
            d[k] = str(v)
        elif isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, str):
            trimmed = v.strip()
            if (trimmed.startswith("{") and trimmed.endswith("}")) or (
                trimmed.startswith("[") and trimmed.endswith("]")
            ):
                try:
                    d[k] = json.loads(trimmed)
                    continue
                except json.JSONDecodeError:
                    pass
            d[k] = v
        else:
            d[k] = v
    return d


def rows_to_dicts(rows: list[asyncpg.Record]) -> list[dict]:
    """Convert a list of asyncpg Records to JSON-safe dicts."""
    return [row_to_dict(r) for r in rows]


def float_or_none(value) -> float | None:
    """Safely convert to float, returning None on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
