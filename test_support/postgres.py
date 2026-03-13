"""Helpers for Postgres-backed integration tests."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg


def _read_dotenv_database_url(path: Path) -> str:
    if not path.is_file():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "DATABASE_URL":
            continue
        return value.strip().strip("'\"")
    return ""


def _discover_test_database_url() -> str:
    direct = os.environ.get("STEWARDOS_TEST_DATABASE_URL", "").strip()
    if direct:
        return direct

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    for base in (Path.cwd(), Path(__file__).resolve().parent):
        for candidate in (base, *base.parents):
            discovered = _read_dotenv_database_url(candidate / ".env")
            if discovered:
                return discovered
    return ""


STEWARDOS_TEST_DATABASE_URL = _discover_test_database_url()

_CREATE_SCHEMA_RE = re.compile(r"CREATE SCHEMA IF NOT EXISTS\s+\w+\s*;", re.IGNORECASE)
_SEARCH_PATH_RE = re.compile(r"SET search_path TO\s+\w+\s*;", re.IGNORECASE)
_SOURCE_SCHEMA_RE = re.compile(r"CREATE SCHEMA IF NOT EXISTS\s+(\w+)\s*;", re.IGNORECASE)


def _rewrite_schema_sql(schema_sql: str, schema_name: str) -> str:
    source_schema_match = _SOURCE_SCHEMA_RE.search(schema_sql)
    source_schema = source_schema_match.group(1) if source_schema_match else None
    rewritten = _CREATE_SCHEMA_RE.sub(
        f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";',
        schema_sql,
        count=1,
    )
    rewritten = _SEARCH_PATH_RE.sub(
        f'SET search_path TO "{schema_name}", public;',
        rewritten,
        count=1,
    )
    if source_schema:
        rewritten = re.sub(
            rf"\b{re.escape(source_schema)}\.",
            f'"{schema_name}".',
            rewritten,
        )
        rewritten = re.sub(
            rf"(\bON\s+SCHEMA\s+){re.escape(source_schema)}\b",
            rf'\1"{schema_name}"',
            rewritten,
        )
        rewritten = re.sub(
            rf"(\bIN\s+SCHEMA\s+){re.escape(source_schema)}\b",
            rf'\1"{schema_name}"',
            rewritten,
        )
    return rewritten


@asynccontextmanager
async def provision_test_schema(schema_sql: str, *, schema_prefix: str = "stewardos_it"):
    """Create an isolated schema, apply schema SQL, and yield a scoped pool."""

    if not STEWARDOS_TEST_DATABASE_URL:
        raise RuntimeError("STEWARDOS_TEST_DATABASE_URL is not configured")

    schema_name = f"{schema_prefix}_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(STEWARDOS_TEST_DATABASE_URL)
    pool: asyncpg.Pool | None = None
    try:
        rewritten_sql = _rewrite_schema_sql(schema_sql, schema_name)
        await admin.execute(rewritten_sql)
        pool = await asyncpg.create_pool(
            STEWARDOS_TEST_DATABASE_URL,
            min_size=1,
            max_size=4,
            server_settings={"search_path": f"{schema_name},public"},
        )
        yield pool
    finally:
        if pool is not None:
            await pool.close()
        if admin.is_in_transaction():
            await admin.execute("ROLLBACK")
        await admin.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        await admin.close()
