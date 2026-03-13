from __future__ import annotations

import asyncio
import os
import sys

import pytest
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as policy_server


class _FakeCongressClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_recent_bills(self, days_back, limit):
        return [{"bill_id": "HR-1", "title": "Test Bill"}]

    async def get_upcoming_hearings(self, days_ahead, limit):
        raise ValueError("invalid hearing request")


class _FakeGovInfoClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_federal_rules(self, days_back, days_ahead, limit):
        raise ValueError("missing GOVINFO_API_KEY")


def test_get_recent_bills_returns_bulk_results(monkeypatch):
    monkeypatch.setattr(policy_server, "CongressBulkClient", _FakeCongressClient)

    result = asyncio.run(policy_server.get_recent_bills(days_back=7, limit=5))

    assert result == [{"bill_id": "HR-1", "title": "Test Bill"}]


def test_get_upcoming_hearings_translates_value_error(monkeypatch):
    monkeypatch.setattr(policy_server, "CongressBulkClient", _FakeCongressClient)

    with pytest.raises(ToolError, match="invalid hearing request"):
        asyncio.run(policy_server.get_upcoming_hearings(days_ahead=14, limit=10))


def test_get_federal_rules_translates_value_error(monkeypatch):
    monkeypatch.setattr(policy_server, "GovInfoBulkClient", _FakeGovInfoClient)

    with pytest.raises(ToolError, match="missing GOVINFO_API_KEY"):
        asyncio.run(policy_server.get_federal_rules(days_back=14, days_ahead=7, limit=10))
