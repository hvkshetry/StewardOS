"""Regression tests for finance-graph server startup lifecycle."""

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
        self.closed = False

    def acquire(self):
        return _FakeAcquire(self.conn)

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_lifespan_initializes_and_closes_pool(monkeypatch):
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

    async with server_module.lifespan(server_module.mcp):
        active_pool = await server_module.get_pool()
        assert active_pool is pool
        assert server_module._initialized is True

    assert len(create_calls) == 1
    assert len(migration_calls) == 1
    assert migration_calls[0][1]["migration_table"] == "finance.schema_migrations"
    assert pool.closed is True
    assert server_module._pool is None
    assert server_module._initialized is False
