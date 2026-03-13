"""DI-based tests for estate-planning people module."""

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def people_mcp(fake_mcp, get_pool):
    from people import register_people_tools
    register_people_tools(fake_mcp, get_pool)
    return fake_mcp


class TestListPeople:
    async def test_returns_people(self, people_mcp, pool):
        pool.fetch.return_value = [
            FakeRecord(id=1, legal_name="Alice", preferred_name="Ali",
                       citizenship=["US"], residency_status="citizen",
                       death_date=None, incapacity_status=None),
        ]
        result = await people_mcp.call("list_people")
        assert len(result["data"]) == 1
        assert result["data"][0]["legal_name"] == "Alice"

    async def test_empty(self, people_mcp, pool):
        pool.fetch.return_value = []
        result = await people_mcp.call("list_people")
        assert result["data"] == []


class TestGetPerson:
    async def test_found(self, people_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(
            id=1, legal_name="Alice", preferred_name="Ali",
            citizenship=["US"], residency_status="citizen",
            death_date=None, incapacity_status=None,
        )
        pool.fetch.return_value = []  # ownership, docs, relationships
        result = await people_mcp.call("get_person", person_id=1)
        assert result["data"]["legal_name"] == "Alice"
        assert "ownership" in result["data"]
        assert "documents" in result["data"]
        assert "relationships" in result["data"]

    async def test_not_found(self, people_mcp, pool):
        pool.fetchrow.return_value = None
        result = await people_mcp.call("get_person", person_id=999)
        assert result["status"] == "error"
        assert result["errors"][0]["message"] == "Person 999 not found"


class TestUpsertPerson:
    async def test_insert(self, people_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(id=1, legal_name="Bob")
        result = await people_mcp.call(
            "upsert_person", legal_name="Bob", date_of_birth="1990-01-15"
        )
        assert result["data"]["id"] == 1
        assert result["data"]["legal_name"] == "Bob"

    async def test_update(self, people_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(id=5, legal_name="Bob Updated")
        result = await people_mcp.call(
            "upsert_person", legal_name="Bob Updated", person_id=5
        )
        assert result["data"]["id"] == 5

    async def test_invalid_date(self, people_mcp, pool):
        result = await people_mcp.call(
            "upsert_person", legal_name="Test", date_of_birth="not-a-date"
        )
        assert result["status"] == "error"


class TestSetPersonRelationship:
    async def test_self_reference_rejected(self, people_mcp, pool):
        result = await people_mcp.call(
            "set_person_relationship",
            person_id=1, related_person_id=1, relationship_type="spouse",
        )
        assert result["status"] == "error"
        assert "must differ" in result["errors"][0]["message"]

    async def test_creates_relationship(self, people_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(
            id=10, person_id=1, related_person_id=2,
            relationship_type="spouse", start_date=None, end_date=None,
            jurisdiction_code=None,
        )
        result = await people_mcp.call(
            "set_person_relationship",
            person_id=1, related_person_id=2, relationship_type="spouse",
        )
        assert result["data"]["id"] == 10

    async def test_end_before_start_rejected(self, people_mcp, pool):
        result = await people_mcp.call(
            "set_person_relationship",
            person_id=1, related_person_id=2, relationship_type="spouse",
            start_date="2020-01-01", end_date="2019-01-01",
        )
        assert result["status"] == "error"
