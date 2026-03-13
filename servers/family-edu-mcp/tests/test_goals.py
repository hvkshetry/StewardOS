"""DI-based tests for family-edu goals module."""

import json

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def goals_mcp(fake_mcp, get_pool):
    from goals import register_goal_tools
    register_goal_tools(fake_mcp, get_pool)
    return fake_mcp


class TestUpsertGoal:
    async def test_learner_not_found(self, goals_mcp, pool):
        conn = pool._conn
        conn.fetchrow.return_value = None  # _fetch_learner_or_none returns None
        result = await goals_mcp.call(
            "upsert_goal", learner_id=999, title="Learn piano"
        )
        assert "error" in result

    async def test_invalid_target_date(self, goals_mcp, pool):
        result = await goals_mcp.call(
            "upsert_goal", learner_id=1, title="Learn piano",
            target_date="not-a-date",
        )
        assert "error" in result

    async def test_create_goal(self, goals_mcp, pool):
        conn = pool._conn
        # First fetchrow: _fetch_learner_or_none
        # Second fetchrow: INSERT goal
        conn.fetchrow.side_effect = [
            FakeRecord(id=1, display_name="Alice", date_of_birth="2020-01-01", metadata="{}"),
            FakeRecord(id=10, learner_id=1, title="Learn piano",
                       description=None, goal_type=None, status="open",
                       target_date=None, success_criteria="{}",
                       owner=None),
        ]
        result = await goals_mcp.call(
            "upsert_goal", learner_id=1, title="Learn piano"
        )
        assert result["title"] == "Learn piano"
        assert result["status"] == "open"

    async def test_update_goal_not_found(self, goals_mcp, pool):
        conn = pool._conn
        conn.fetchrow.side_effect = [
            FakeRecord(id=1, display_name="Alice", date_of_birth="2020-01-01", metadata="{}"),
            None,  # goal update returns None
        ]
        result = await goals_mcp.call(
            "upsert_goal", learner_id=1, title="Updated", goal_id=999
        )
        assert "error" in result


class TestGetOpenActions:
    async def test_returns_actions(self, goals_mcp, pool):
        conn = pool._conn
        conn.fetch.return_value = [
            FakeRecord(id=1, learner_id=1, title="Practice scales",
                       status="open", learner_name="Alice",
                       goal_title="Learn piano", due_date="2024-04-01"),
        ]
        result = await goals_mcp.call("get_open_actions", learner_id=1)
        assert len(result) == 1
        assert result[0]["title"] == "Practice scales"

    async def test_empty(self, goals_mcp, pool):
        conn = pool._conn
        conn.fetch.return_value = []
        result = await goals_mcp.call("get_open_actions")
        assert result == []
