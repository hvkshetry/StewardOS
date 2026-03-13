"""DI-based tests for health-graph status module."""

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def status_mcp(fake_mcp, get_pool, ensure_initialized):
    from status import register_status_tools
    register_status_tools(fake_mcp, get_pool, ensure_initialized)
    return fake_mcp


class TestHealthGraphStatus:
    async def test_returns_status(self, status_mcp, pool):
        pool._conn.fetch.return_value = [
            FakeRecord(id=1, source_name="opentargets", status="success",
                       rows_read=100, rows_written=1, started_at="2024-01-01"),
        ]
        pool._conn.fetchrow.return_value = FakeRecord(
            subjects=5, callsets=2, genotype_calls=100,
            clinical_assertions=10, pgx_recommendations=3,
            observations=50, coverages=2, coverage_determinations=1,
            document_metadata=8, literature_evidence=20,
        )
        result = await status_mcp.call("health_graph_status")
        assert result["status"] == "ok"
        assert result["errors"] == []
        assert result["data"]["counts"]["subjects"] == 5
        assert len(result["data"]["latest_runs"]) == 1


class TestRefreshSource:
    async def test_invalid_source_returns_error(self, status_mcp, pool):
        result = await status_mcp.call(
            "refresh_source", source_name="",
        )
        assert result["status"] == "error"
        assert result["errors"][0]["message"]

    async def test_unsupported_source_noop(self, status_mcp, pool):
        # _start_run calls conn.fetchrow (INSERT RETURNING id)
        pool._conn.fetchrow.return_value = FakeRecord(id=1)
        result = await status_mcp.call(
            "refresh_source", source_name="some_source",
        )
        assert result["status"] == "ok"
        assert "No-op" in result["data"]["message"]
