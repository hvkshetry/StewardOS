"""Shared test infrastructure for health-graph-mcp tests."""

import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parents[1])
repo_root = str(Path(__file__).resolve().parents[3])

for p in (server_root, repo_root):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_support.db import FakeRecord, mock_asyncpg_pool  # noqa: E402
from test_support.mcp import FakeMCP  # noqa: E402


@pytest.fixture
def fake_mcp():
    return FakeMCP()


@pytest.fixture
def pool():
    return mock_asyncpg_pool()


@pytest.fixture
def get_pool(pool):
    async def _get_pool():
        return pool
    return _get_pool


@pytest.fixture
def ensure_initialized():
    async def _noop():
        pass
    return _noop
