"""DI-based tests for health-graph subjects module."""

import pytest

from test_support.db import FakeRecord


@pytest.fixture
def subjects_mcp(fake_mcp, get_pool, ensure_initialized):
    from subjects import register_subject_tools
    register_subject_tools(fake_mcp, get_pool, ensure_initialized)
    return fake_mcp


class TestListSubjects:
    async def test_returns_subjects(self, subjects_mcp, pool):
        pool._conn.fetch.return_value = [
            FakeRecord(id=1, display_name="Alice", date_of_birth="1990-01-01",
                       sex_at_birth="female", metadata={}),
        ]
        result = await subjects_mcp.call("list_subjects")
        assert result["status"] == "ok"
        assert len(result["data"]) == 1
        assert result["data"][0]["display_name"] == "Alice"

    async def test_empty(self, subjects_mcp, pool):
        pool._conn.fetch.return_value = []
        result = await subjects_mcp.call("list_subjects")
        assert result["data"] == []


class TestUpsertSubject:
    async def test_insert(self, subjects_mcp, pool):
        pool._conn.fetchrow.return_value = FakeRecord(
            id=1, display_name="Bob", date_of_birth=None,
            sex_at_birth=None, metadata={},
        )
        result = await subjects_mcp.call(
            "upsert_subject", display_name="Bob",
        )
        assert result["status"] == "ok"
        assert result["data"]["display_name"] == "Bob"
        assert result["data"]["operation_status"] == "created"

    async def test_identifier_match_updates_existing_subject(self, subjects_mcp, pool):
        pool._conn.fetchrow.side_effect = [
            FakeRecord(subject_id=1),
            FakeRecord(id=1, display_name="Bob", date_of_birth="1990-01-01",
                       sex_at_birth="male", metadata={}),
            FakeRecord(id=10, subject_id=1, id_type="MRN", id_value="12345", source_name="hospital"),
            FakeRecord(id=10, subject_id=1, id_type="MRN", id_value="12345", source_name="hospital"),
        ]
        result = await subjects_mcp.call(
            "upsert_subject", display_name="Bob",
            date_of_birth="1990-01-01", sex_at_birth="male",
            identifiers=[{"id_type": "mrn", "id_value": "12345", "source_name": "hospital"}],
        )
        assert result["status"] == "ok"
        assert result["data"]["display_name"] == "Bob"
        assert result["data"]["operation_status"] == "updated"
        assert result["data"]["identifiers"][0]["id_type"] == "MRN"

    async def test_display_name_only_calls_do_not_dedupe(self, subjects_mcp, pool):
        pool._conn.fetchrow.side_effect = [
            FakeRecord(id=1, display_name="Bob", date_of_birth=None, sex_at_birth=None, metadata={}),
            FakeRecord(id=2, display_name="Bob", date_of_birth=None, sex_at_birth=None, metadata={}),
        ]

        first = await subjects_mcp.call("upsert_subject", display_name="Bob")
        second = await subjects_mcp.call("upsert_subject", display_name="Bob")

        assert first["data"]["id"] == 1
        assert second["data"]["id"] == 2
        assert first["data"]["operation_status"] == "created"
        assert second["data"]["operation_status"] == "created"


class TestLinkSubjectIdentifier:
    async def test_links_identifier(self, subjects_mcp, pool):
        pool._conn.fetchval.return_value = 1
        pool._conn.fetchrow.side_effect = [
            None,
            FakeRecord(
                id=10, subject_id=1, id_type="MRN", id_value="12345",
                source_name="hospital",
            ),
        ]
        result = await subjects_mcp.call(
            "link_subject_identifier",
            subject_id=1, id_type="MRN", id_value="12345",
            source_name="hospital",
        )
        assert result["status"] == "ok"
        assert result["data"]["id_type"] == "MRN"
        assert result["data"]["id_value"] == "12345"
