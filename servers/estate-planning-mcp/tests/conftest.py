"""Shared test infrastructure for estate-planning-mcp tests."""

import sys
from pathlib import Path

import pytest

# Ensure server root is importable (for domain modules like people.py, etc.)
server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

# Ensure repo-level test_support package is importable
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
    """Pre-configured mock pool. Tests can further configure via pool.fetch.return_value etc."""
    return mock_asyncpg_pool()


@pytest.fixture
def get_pool(pool):
    """Injectable get_pool callable that returns the mock pool."""
    async def _get_pool():
        return pool
    return _get_pool
