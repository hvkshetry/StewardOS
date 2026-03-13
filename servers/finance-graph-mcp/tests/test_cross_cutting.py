"""DI-based tests for finance-graph cross_cutting module."""

import pytest

from test_support.db import FakeRecord


@pytest.fixture
def cc_mcp(fake_mcp, get_pool):
    from cross_cutting import register_cross_cutting_tools
    register_cross_cutting_tools(fake_mcp, get_pool)
    return fake_mcp


class TestGetNetWorth:
    async def test_assets_only(self, cc_mcp, pool):
        pool.fetch.side_effect = [
            # asset_rows
            [FakeRecord(jurisdiction="US-CA", currency="USD", asset_value=500000)],
            # liability_rows
            [],
        ]
        result = await cc_mcp.call("get_net_worth")
        assert result["status"] == "ok"
        assert len(result["data"]) == 1
        assert result["data"][0]["asset_value"] == 500000
        assert result["data"][0]["liability_value"] == 0.0
        assert result["data"][0]["net_worth_after_liabilities"] == 500000
        assert result["data"][0]["ownership_basis"] == "legal_title"
        assert result["provenance"]["ownership_basis"] == "legal_title"

    async def test_with_liabilities(self, cc_mcp, pool):
        pool.fetch.side_effect = [
            [FakeRecord(jurisdiction="US-CA", currency="USD", asset_value=500000)],
            [FakeRecord(jurisdiction="US-CA", currency="USD", liability_value=200000)],
        ]
        result = await cc_mcp.call("get_net_worth")
        assert result["data"][0]["net_worth_after_liabilities"] == 300000

    async def test_empty(self, cc_mcp, pool):
        pool.fetch.side_effect = [[], []]
        result = await cc_mcp.call("get_net_worth")
        assert result["data"] == []

    async def test_person_rollup_uses_single_person_param_and_breakdown(self, cc_mcp, pool):
        pool.fetch.side_effect = [
            [
                FakeRecord(
                    jurisdiction="US-MA",
                    currency="USD",
                    direct_asset_value=100000,
                    lookthrough_asset_value=250000,
                ),
            ],
            [
                FakeRecord(
                    jurisdiction="US-MA",
                    currency="USD",
                    direct_liability_value=50000,
                    lookthrough_liability_value=125000,
                ),
            ],
        ]

        result = await cc_mcp.call("get_net_worth", person_id=7)

        assert result["data"] == [
            {
                "jurisdiction": "US-MA",
                "currency": "USD",
                "asset_value": 350000.0,
                "liability_value": 175000.0,
                "net_worth_after_liabilities": 175000.0,
                "direct_asset_value": 100000.0,
                "lookthrough_asset_value": 250000.0,
                "direct_liability_value": 50000.0,
                "lookthrough_liability_value": 125000.0,
                "ownership_basis": "legal_title",
            }
        ]
        assert pool.fetch.await_args_list[0].args[1:] == (7,)
        assert pool.fetch.await_args_list[1].args[1:] == (7,)

    async def test_rejects_unsupported_ownership_basis(self, cc_mcp):
        result = await cc_mcp.call("get_net_worth", ownership_basis="beneficial")

        assert result["status"] == "error"
        assert result["errors"][0]["code"] == "unsupported_ownership_basis"


class TestGetUpcomingDates:
    async def test_returns_dates(self, cc_mcp, pool):
        pool.fetch.return_value = [
            FakeRecord(id=1, title="Annual Report", due_date="2024-03-15",
                       entity_name="Trust A", asset_name=None,
                       person_name=None, jurisdiction="US-CA"),
        ]
        result = await cc_mcp.call("get_upcoming_dates", days=60)
        assert len(result["data"]) == 1
        assert result["data"][0]["title"] == "Annual Report"


class TestLinkDocument:
    async def test_requires_paperless_doc_id(self, cc_mcp):
        result = (
            await cc_mcp.call(
                "link_document",
                title="Trust Agreement",
                doc_type="trust_agreement",
            )
        )
        assert result["status"] == "error"
        assert result["errors"][0]["message"] == "paperless_doc_id is required"

    async def test_rejects_unknown_jurisdiction(self, cc_mcp, pool):
        pool.fetchval.return_value = None
        result = (
            await cc_mcp.call(
                "link_document",
                title="Trust Agreement",
                doc_type="trust_agreement",
                paperless_doc_id=100,
                jurisdiction_code="ZZ-UNKNOWN",
            )
        )
        assert result["status"] == "error"
        assert result["errors"][0]["message"] == "Unknown jurisdiction_code: ZZ-UNKNOWN"

    async def test_creates_document_and_metadata(self, cc_mcp, pool):
        pool.fetchval.return_value = 10
        pool._conn.fetchrow.side_effect = [
            FakeRecord(id=1, title="Trust Agreement", paperless_doc_id=100),
            FakeRecord(paperless_doc_id=100, doc_purpose_type="trust_agreement", status="active"),
        ]
        result = await cc_mcp.call(
            "link_document",
            title="Trust Agreement",
            doc_type="trust_agreement",
            paperless_doc_id=100,
            entity_id=1,
            jurisdiction_code="US-MA",
        )
        assert result["status"] == "ok"
        assert result["data"]["title"] == "Trust Agreement"
        assert result["data"]["doc_metadata"]["status"] == "active"
