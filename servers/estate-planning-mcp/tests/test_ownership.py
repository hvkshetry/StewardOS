"""DI-based tests for estate-planning ownership module."""

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def ownership_mcp(fake_mcp, get_pool):
    from ownership import register_ownership_tools
    register_ownership_tools(fake_mcp, get_pool)
    return fake_mcp


class TestGetOwnershipGraph:
    async def test_full_graph(self, ownership_mcp, pool):
        pool.fetch.return_value = [
            FakeRecord(owner_name="Alice", owned_name="Trust A", percentage=100.0),
        ]
        result = await ownership_mcp.call("get_ownership_graph")
        assert len(result["data"]) == 1
        assert result["data"][0]["owner_name"] == "Alice"

    async def test_person_filtered(self, ownership_mcp, pool):
        pool.fetch.return_value = [
            FakeRecord(entity_id=1, effective_pct=50.0),
        ]
        result = await ownership_mcp.call("get_ownership_graph", person_id=1)
        assert len(result["data"]) == 1


class TestSetOwnership:
    async def test_new_ownership(self, ownership_mcp, pool):
        # No existing path
        pool.fetchrow.side_effect = [
            None,  # existing check
            FakeRecord(id=1),  # insert
            FakeRecord(id=10),  # beneficial_interests insert
        ]
        result = await ownership_mcp.call(
            "set_ownership",
            percentage=50.0,
            owner_person_id=1,
            owned_entity_id=2,
        )
        assert result["data"]["id"] == 1
        assert result["status"] == "ok"
        assert result["data"]["beneficial_interest_id"] == 10

    async def test_update_existing(self, ownership_mcp, pool):
        pool.fetchrow.side_effect = [
            FakeRecord(id=5),  # existing found
            FakeRecord(id=5),  # update
            FakeRecord(id=20),  # beneficial_interests upsert
        ]
        result = await ownership_mcp.call(
            "set_ownership",
            percentage=75.0,
            owner_person_id=1,
            owned_entity_id=2,
        )
        assert result["data"]["id"] == 5


class TestSetBeneficialInterest:
    async def test_requires_exactly_one_owner(self, ownership_mcp, pool):
        result = await ownership_mcp.call(
            "set_beneficial_interest",
            interest_type="economic",
            owner_person_id=1,
            owner_entity_id=2,
            subject_entity_id=3,
        )
        assert result["status"] == "error"

    async def test_requires_exactly_one_subject(self, ownership_mcp, pool):
        result = await ownership_mcp.call(
            "set_beneficial_interest",
            interest_type="economic",
            owner_person_id=1,
            subject_entity_id=3,
            subject_asset_id=4,
        )
        assert result["status"] == "error"

    async def test_invalid_direct_or_indirect(self, ownership_mcp, pool):
        result = await ownership_mcp.call(
            "set_beneficial_interest",
            interest_type="economic",
            owner_person_id=1,
            subject_entity_id=3,
            direct_or_indirect="maybe",
        )
        assert result["status"] == "error"

    async def test_valid_insert(self, ownership_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(
            id=1, interest_type="economic", direct_or_indirect="direct",
            beneficial_flag=True, share_exact=50.0,
        )
        result = await ownership_mcp.call(
            "set_beneficial_interest",
            interest_type="economic",
            owner_person_id=1,
            subject_entity_id=3,
            direct_or_indirect="direct",
            beneficial_flag=True,
            share_exact=50.0,
        )
        assert result["data"]["interest_type"] == "economic"
