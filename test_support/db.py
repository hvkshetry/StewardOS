"""Mock database utilities for testing MCP servers without a real database."""

from unittest.mock import AsyncMock, MagicMock


class FakeRecord(dict):
    """A dict subclass that supports attribute access like asyncpg.Record."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def mock_asyncpg_pool(fetch_results=None, fetchrow_result=None, fetchval_result=None, execute_result=None):
    """Create a mock asyncpg pool with configurable return values."""

    pool = AsyncMock()
    conn = AsyncMock()

    conn.fetch = AsyncMock(return_value=fetch_results or [])
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.fetchval = AsyncMock(return_value=fetchval_result)
    conn.execute = AsyncMock(return_value=execute_result or "INSERT 0 1")

    txn_ctx = MagicMock()
    txn_ctx.__aenter__ = AsyncMock(return_value=None)
    txn_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn_ctx)

    pool.fetch = AsyncMock(return_value=fetch_results or [])
    pool.fetchrow = AsyncMock(return_value=fetchrow_result)
    pool.fetchval = AsyncMock(return_value=fetchval_result)
    pool.execute = AsyncMock(return_value=execute_result or "INSERT 0 1")

    acq_ctx = MagicMock()
    acq_ctx.__aenter__ = AsyncMock(return_value=conn)
    acq_ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq_ctx)

    pool._conn = conn
    return pool
