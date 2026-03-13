"""Unit tests for shared migration helpers."""

from __future__ import annotations

from pathlib import Path

from stewardos_lib.migrations import _resolve_sql_text, ensure_migrations_sync


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows: list[tuple[str]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params=None):
        self._conn.executed.append((sql, params))
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select version from tax.schema_migrations"):
            self._rows = [(name,) for name in sorted(self._conn.applied)]
            return
        if normalized.startswith("insert into tax.schema_migrations") and params:
            self._conn.applied.add(str(params[0]))
            self._rows = []
            return
        self._rows = []

    def fetchall(self):
        return list(self._rows)


class _FakeConn:
    def __init__(self):
        self.applied: set[str] = set()
        self.executed: list[tuple[str, object]] = []

    def cursor(self):
        return _FakeCursor(self)


def test_resolve_sql_text_expands_relative_includes(tmp_path: Path) -> None:
    included = tmp_path / "included.sql"
    included.write_text("SELECT 1;", encoding="utf-8")
    root = tmp_path / "root.sql"
    root.write_text("\\i included.sql\nSELECT 2;\n", encoding="utf-8")

    resolved = _resolve_sql_text(root)

    assert "SELECT 1;" in resolved
    assert "SELECT 2;" in resolved
    assert "\\i" not in resolved


def test_ensure_migrations_sync_supports_custom_migration_column(tmp_path: Path) -> None:
    (tmp_path / "001_init.sql").write_text("SELECT 42;", encoding="utf-8")
    conn = _FakeConn()

    missing = ensure_migrations_sync(
        conn,
        migrations_dir=tmp_path,
        auto_apply=True,
        migration_table="tax.schema_migrations",
        migration_name_column="version",
    )

    assert missing == ["001_init.sql"]
    assert "001_init.sql" in conn.applied
    executed_sql = "\n".join(str(sql) for sql, _ in conn.executed)
    assert "SELECT 42;" in executed_sql
    assert "version" in executed_sql


def test_ensure_migrations_sync_creates_schema_qualified_ledger_table(tmp_path: Path) -> None:
    (tmp_path / "001_init.sql").write_text("SELECT 42;", encoding="utf-8")
    conn = _FakeConn()

    ensure_migrations_sync(
        conn,
        migrations_dir=tmp_path,
        auto_apply=True,
        migration_table="family_edu.schema_migrations",
    )

    ddl_sql = str(conn.executed[0][0])
    assert "CREATE SCHEMA IF NOT EXISTS family_edu" in ddl_sql
    assert "CREATE TABLE IF NOT EXISTS family_edu.schema_migrations" in ddl_sql


def test_ensure_migrations_sync_rejects_public_schema_ledger(tmp_path: Path) -> None:
    (tmp_path / "001_init.sql").write_text("SELECT 42;", encoding="utf-8")
    conn = _FakeConn()

    try:
        ensure_migrations_sync(
            conn,
            migrations_dir=tmp_path,
            auto_apply=True,
            migration_table="public.schema_migrations",
        )
    except ValueError as exc:
        assert "app schema" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for public schema migration ledger")
