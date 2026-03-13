"""Regression tests for health-graph server initialization."""

from __future__ import annotations

import asyncio

import pytest


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self):
        self.conn = object()

    def acquire(self):
        return _FakeAcquire(self.conn)


@pytest.mark.asyncio
async def test_ensure_initialized_uses_health_schema_migration_table(monkeypatch):
    import server as server_module

    pool = _FakePool()
    create_calls: list[tuple] = []
    migration_calls: list[tuple] = []

    async def fake_create_server_pool(*args, **kwargs):
        create_calls.append((args, kwargs))
        return pool

    async def fake_ensure_migrations(conn, **kwargs):
        migration_calls.append((conn, kwargs))

    monkeypatch.setattr(server_module, "create_server_pool", fake_create_server_pool)
    monkeypatch.setattr(server_module, "ensure_migrations", fake_ensure_migrations)

    server_module._pool = None
    server_module._initialized = False
    server_module._init_lock = asyncio.Lock()

    await server_module._ensure_initialized()
    active_pool = await server_module._get_pool()

    assert active_pool is pool
    assert len(create_calls) == 1
    assert len(migration_calls) == 1
    assert migration_calls[0][1]["migration_table"] == "health.schema_migrations"
