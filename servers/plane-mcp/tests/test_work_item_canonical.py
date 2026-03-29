"""Tests for canonical Plane work_item tool."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def work_item_mcp(fake_mcp, get_client):
    from tools.work_item import register_work_item_tools

    register_work_item_tools(fake_mcp, get_client)
    return fake_mcp


class TestWorkItemUpsertByExternal:
    async def test_uses_collection_put_route(self, work_item_mcp):
        with patch("tools.work_item.api_put", new_callable=AsyncMock) as mock_put:
            mock_put.return_value = {
                "id": "wi-external",
                "name": "Delegated case",
                "external_source": "gmail_thread",
                "external_id": "thread-123",
            }

            result = await work_item_mcp.call(
                "work_item",
                operation="upsert_by_external",
                workspace_slug="test-workspace",
                project_id="proj-1",
                external_source="gmail_thread",
                external_id="thread-123",
                title="Delegated case",
            )

        assert result["ok"] is True
        assert result["data"]["id"] == "wi-external"
        assert mock_put.call_args.args[0] == "/workspaces/test-workspace/projects/proj-1/work-items/"
        assert mock_put.call_args.args[1]["external_source"] == "gmail_thread"
        assert mock_put.call_args.args[1]["external_id"] == "thread-123"
