"""Real-Postgres integration tests for health subject identity semantics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

repo_root = str(Path(__file__).resolve().parents[3])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from subjects import register_subject_tools
from test_support.mcp import FakeMCP
from test_support.postgres import STEWARDOS_TEST_DATABASE_URL, provision_test_schema

SCHEMA_SQL = Path(server_root, "schema.sql").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    not STEWARDOS_TEST_DATABASE_URL,
    reason="STEWARDOS_TEST_DATABASE_URL is not configured",
)


@pytest.fixture
async def pg_pool():
    async with provision_test_schema(SCHEMA_SQL, schema_prefix="health_it") as pool:
        yield pool


@pytest.mark.asyncio
async def test_identifier_based_upsert_updates_same_subject(pg_pool):
    async def get_pool():
        return pg_pool

    async def ensure_initialized():
        return None

    mcp = FakeMCP()
    register_subject_tools(mcp, get_pool, ensure_initialized)

    created = await mcp.call(
        "upsert_subject",
        display_name="Taylor Subject",
        identifiers=[{"id_type": "mrn", "id_value": "12345"}],
    )
    updated = await mcp.call(
        "upsert_subject",
        display_name="Taylor Subject Revised",
        identifiers=[{"id_type": "MRN", "id_value": "12345"}],
    )

    assert created["status"] == "ok"
    assert updated["status"] == "ok"
    assert created["data"]["operation_status"] == "created"
    assert updated["data"]["operation_status"] == "updated"
    assert updated["data"]["id"] == created["data"]["id"]
    assert updated["data"]["display_name"] == "Taylor Subject Revised"


@pytest.mark.asyncio
async def test_display_name_only_calls_create_distinct_subjects(pg_pool):
    async def get_pool():
        return pg_pool

    async def ensure_initialized():
        return None

    mcp = FakeMCP()
    register_subject_tools(mcp, get_pool, ensure_initialized)

    first = await mcp.call("upsert_subject", display_name="Jordan Duplicate")
    second = await mcp.call("upsert_subject", display_name="Jordan Duplicate")

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["data"]["operation_status"] == "created"
    assert second["data"]["operation_status"] == "created"
    assert first["data"]["id"] != second["data"]["id"]
