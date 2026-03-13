"""Shared test infrastructure for finance-graph-mcp tests."""

import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

repo_root = str(Path(__file__).resolve().parents[3])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from test_support.db import FakeRecord, mock_asyncpg_pool
from test_support.mcp import FakeMCP


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
