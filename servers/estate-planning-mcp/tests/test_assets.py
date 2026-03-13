"""DI-based tests for estate-planning assets module."""

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def assets_mcp(fake_mcp, get_pool):
    from assets import register_assets_tools
    register_assets_tools(fake_mcp, get_pool)
    return fake_mcp


class TestListAssets:
    async def test_returns_assets(self, assets_mcp, pool):
        pool.fetch.return_value = [
            FakeRecord(
                id=1, name="Primary Residence", asset_type="real_estate",
                current_valuation_amount=500000, valuation_currency="USD",
                valuation_date="2024-01-01", jurisdiction="US-CA",
                owner_name="Alice", asset_class_code="real_estate",
                asset_subclass_code="real_estate_residential",
                country_code="US", region_code="CA", property_type="residential",
            ),
        ]
        result = await assets_mcp.call("list_assets")
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Primary Residence"

    async def test_empty_list(self, assets_mcp, pool):
        pool.fetch.return_value = []
        result = await assets_mcp.call("list_assets")
        assert result["data"] == []

    async def test_filter_by_class(self, assets_mcp, pool):
        pool.fetch.return_value = []
        await assets_mcp.call("list_assets", asset_class_code="real_estate")
        call_args = pool.fetch.call_args
        assert "ac.code = $1" in call_args[0][0]
        assert call_args[0][1] == "real_estate"

    async def test_filter_by_owner_entity(self, assets_mcp, pool):
        pool.fetch.return_value = []
        await assets_mcp.call("list_assets", owner_entity_id=5)
        call_args = pool.fetch.call_args
        assert "a.owner_entity_id = $1" in call_args[0][0]
        assert call_args[0][1] == 5


class TestUpsertAsset:
    async def test_missing_class_code(self, assets_mcp, pool):
        result = await assets_mcp.call(
            "upsert_asset",
            name="Test", asset_class_code="", asset_subclass_code="sub",
            jurisdiction_code="US", valuation_currency="USD",
        )
        assert result["status"] == "error"
        assert "asset_class_code" in result["errors"][0]["message"]

    async def test_invalid_currency(self, assets_mcp, pool):
        result = await assets_mcp.call(
            "upsert_asset",
            name="Test", asset_class_code="real_estate",
            asset_subclass_code="real_estate_residential",
            jurisdiction_code="US", valuation_currency="X",
        )
        assert result["status"] == "error"
        assert "ISO-4217" in result["errors"][0]["message"]

    async def test_unknown_class_returns_valid_codes(self, assets_mcp, pool):
        pool.fetchrow.return_value = None
        pool.fetch.return_value = [FakeRecord(code="real_estate"), FakeRecord(code="equities")]
        result = await assets_mcp.call(
            "upsert_asset",
            name="Test", asset_class_code="nonexistent",
            asset_subclass_code="sub",
            jurisdiction_code="US", valuation_currency="USD",
        )
        assert result["status"] == "error"
        assert result["data"]["valid_asset_class_codes"] == ["real_estate", "equities"]

    async def test_insert_new_asset(self, assets_mcp, pool):
        # Simulate class, subclass, jurisdiction lookups then insert
        pool.fetchrow.side_effect = [
            FakeRecord(id=1, code="real_estate"),               # class_row
            FakeRecord(id=10, asset_class_id=1, code="real_estate_residential"),  # subclass_row
        ]
        pool._conn.fetchrow.return_value = FakeRecord(id=99, name="Test Asset")
        pool.fetchval.return_value = 7  # jurisdiction id
        pool.execute.return_value = "INSERT 0 1"

        result = await assets_mcp.call(
            "upsert_asset",
            name="Test Asset", asset_class_code="real_estate",
            asset_subclass_code="real_estate_residential",
            jurisdiction_code="US", valuation_currency="USD",
            owner_person_id=1,
        )
        assert result["data"]["taxonomy_updated"] is True
        assert result["data"]["asset_class_code"] == "real_estate"
