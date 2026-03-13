"""DI-based tests for estate-planning cross_cutting module."""

from __future__ import annotations

import pytest

from test_support.db import FakeRecord


@pytest.fixture
def cc_mcp(fake_mcp, get_pool):
    from cross_cutting import register_cross_cutting_tools

    register_cross_cutting_tools(fake_mcp, get_pool)
    return fake_mcp


class TestGetNetWorth:
    async def test_attaches_ownership_basis_metadata(self, cc_mcp, pool):
        pool.fetch.return_value = [
            FakeRecord(jurisdiction_code="US-CA", total_value=500000, currency="USD"),
        ]

        result = await cc_mcp.call("get_net_worth")

        assert result["status"] == "ok"
        assert result["data"] == [
            {
                "jurisdiction_code": "US-CA",
                "total_value": 500000,
                "currency": "USD",
                "ownership_basis": "legal_title",
            }
        ]
        assert result["provenance"]["ownership_basis"] == "legal_title"

    async def test_rejects_unsupported_ownership_basis(self, cc_mcp):
        result = await cc_mcp.call("get_net_worth", ownership_basis="beneficial")

        assert result["status"] == "error"
        assert result["errors"][0]["code"] == "unsupported_ownership_basis"
