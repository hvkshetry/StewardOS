"""DI-based tests for family-edu learners module."""

import json

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def learner_mcp(fake_mcp, get_pool):
    from learners import register_learner_tools
    register_learner_tools(fake_mcp, get_pool)
    return fake_mcp


class TestListLearners:
    async def test_returns_learners(self, learner_mcp, pool):
        conn = pool._conn
        conn.fetch.return_value = [
            FakeRecord(id=1, display_name="Alice", date_of_birth="2020-06-15", metadata="{}"),
        ]
        result = await learner_mcp.call("list_learners")
        assert len(result) == 1
        assert result[0]["display_name"] == "Alice"
        assert "age_months" in result[0]

    async def test_empty(self, learner_mcp, pool):
        conn = pool._conn
        conn.fetch.return_value = []
        result = await learner_mcp.call("list_learners")
        assert result == []


class TestCreateLearner:
    async def test_valid_create(self, learner_mcp, pool):
        conn = pool._conn
        conn.fetchrow.return_value = FakeRecord(
            id=1, display_name="Bob", date_of_birth="2021-03-10", metadata="{}",
        )
        result = await learner_mcp.call(
            "create_learner", display_name="Bob", date_of_birth="2021-03-10"
        )
        assert result["display_name"] == "Bob"
        assert "age_months" in result

    async def test_invalid_date(self, learner_mcp, pool):
        result = await learner_mcp.call(
            "create_learner", display_name="Test", date_of_birth="not-a-date"
        )
        assert "error" in result


class TestGetLearnerProfile:
    async def test_not_found(self, learner_mcp, pool):
        conn = pool._conn
        conn.fetchrow.return_value = None
        result = await learner_mcp.call("get_learner_profile", learner_id=999)
        assert "error" in result

    async def test_found(self, learner_mcp, pool):
        conn = pool._conn
        conn.fetchrow.side_effect = [
            # learner row
            FakeRecord(id=1, display_name="Alice", date_of_birth="2020-06-15", metadata="{}"),
            # milestone_stats
            FakeRecord(achieved_count=5, pending_count=10, not_applicable_count=0),
            # goal_stats
            FakeRecord(open_goals=2, completed_goals=3),
        ]
        conn.fetch.side_effect = [
            # enrollment_rows
            [],
            # artifact_stats_rows
            [],
        ]
        result = await learner_mcp.call("get_learner_profile", learner_id=1)
        assert result["learner"]["display_name"] == "Alice"
        assert result["milestone_summary"]["achieved_count"] == 5
        assert result["goal_summary"]["open_goals"] == 2
