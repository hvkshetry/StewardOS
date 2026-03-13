"""Shared SQL migration helpers for StewardOS services."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import asyncpg

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INCLUDE_RE = re.compile(r"^\s*\\i\s+(.+?)\s*$")


def _qualified_parts(qualified_name: str) -> tuple[str, str]:
    parts = qualified_name.split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"migration_table must be schema-qualified: {qualified_name}")
    schema_name, table_name = parts
    if not _IDENTIFIER_RE.fullmatch(schema_name) or not _IDENTIFIER_RE.fullmatch(table_name):
        raise ValueError(f"Invalid migration table name: {qualified_name}")
    return schema_name, table_name


def _migration_table_ddl(qualified_name: str, *, migration_name_column: str) -> str:
    schema_name, table_name = _qualified_parts(qualified_name)
    if schema_name == "public":
        raise ValueError("migration_table must use an app schema, not the public schema")
    if not _IDENTIFIER_RE.fullmatch(migration_name_column):
        raise ValueError(f"Invalid migration column name: {migration_name_column}")
    return f"""
        CREATE SCHEMA IF NOT EXISTS {schema_name};
        CREATE TABLE IF NOT EXISTS {schema_name}.{table_name} (
            {migration_name_column} TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """


def _resolve_sql_text(path: Path, *, _stack: tuple[Path, ...] = ()) -> str:
    resolved = path.resolve()
    if resolved in _stack:
        cycle = " -> ".join(str(item) for item in (*_stack, resolved))
        raise RuntimeError(f"SQL include cycle detected: {cycle}")

    lines: list[str] = []
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        match = _INCLUDE_RE.match(raw_line)
        if not match:
            lines.append(raw_line)
            continue
        include_target = match.group(1).strip().strip("'\"")
        include_path = (resolved.parent / include_target).resolve()
        lines.append(_resolve_sql_text(include_path, _stack=(*_stack, resolved)))
    return "\n".join(lines)


def _migration_file_names(path: Path) -> list[str]:
    return sorted(p.name for p in path.glob("*.sql") if p.is_file())


def _missing_migrations(path: Path, applied: set[str]) -> list[str]:
    return [name for name in _migration_file_names(path) if name not in applied]


async def ensure_migrations(
    conn: asyncpg.Connection,
    *,
    migrations_dir: str | Path,
    auto_apply: bool = False,
    migration_table: str,
    migration_name_column: str = "name",
) -> list[str]:
    """Verify or apply SQL migrations in lexical order.

    Returns the list of missing migrations that were detected before any
    optional auto-apply work was performed.
    """

    path = Path(migrations_dir)
    await conn.execute(_migration_table_ddl(migration_table, migration_name_column=migration_name_column))

    rows = await conn.fetch(
        f"SELECT {migration_name_column} FROM {migration_table} ORDER BY {migration_name_column}"
    )
    applied = {str(row[migration_name_column]) for row in rows}
    missing = _missing_migrations(path, applied)

    if missing and not auto_apply:
        raise RuntimeError(
            "Missing required migrations: "
            + ", ".join(missing)
            + ". Apply migrations before starting this service."
        )

    for name in missing:
        sql = _resolve_sql_text(path / name)
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                f"INSERT INTO {migration_table} ({migration_name_column}) VALUES ($1) "
                f"ON CONFLICT ({migration_name_column}) DO NOTHING",
                name,
            )

    return missing


def ensure_migrations_sync(
    conn: Any,
    *,
    migrations_dir: str | Path,
    auto_apply: bool = False,
    migration_table: str,
    migration_name_column: str = "name",
) -> list[str]:
    """Sync variant of ensure_migrations for psycopg-backed services."""

    path = Path(migrations_dir)
    with conn.cursor() as cur:
        cur.execute(_migration_table_ddl(migration_table, migration_name_column=migration_name_column))
        cur.execute(
            f"SELECT {migration_name_column} FROM {migration_table} ORDER BY {migration_name_column}"
        )
        applied = {str(row[0]) for row in cur.fetchall()}
        missing = _missing_migrations(path, applied)
        if missing and not auto_apply:
            raise RuntimeError(
                "Missing required migrations: "
                + ", ".join(missing)
                + ". Apply migrations before starting this service."
            )
        for name in missing:
            cur.execute(_resolve_sql_text(path / name))
            cur.execute(
                f"INSERT INTO {migration_table} ({migration_name_column}) VALUES (%s) "
                f"ON CONFLICT ({migration_name_column}) DO NOTHING",
                (name,),
            )
    return missing
