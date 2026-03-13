"""DI-based tests for plane-mcp view tools."""

from unittest.mock import AsyncMock, patch

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def view_mcp(fake_mcp, get_client, mock_client):
    from tools.views import register_view_tools
    register_view_tools(fake_mcp, get_client)
    return fake_mcp


class TestListViews:
    async def test_returns_views(self, view_mcp):
        with patch("tools.views.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {
                    "id": "view-1",
                    "name": "Overdue Tasks",
                    "description": "All tasks past due date",
                    "query_data": {"target_date__lt": "2026-03-10"},
                    "access": 0,
                    "created_at": "2026-03-01T00:00:00Z",
                    "updated_at": "2026-03-05T00:00:00Z",
                },
                {
                    "id": "view-2",
                    "name": "High Priority",
                    "description": "",
                    "query_data": {"priority": ["high", "urgent"]},
                    "access": 0,
                    "created_at": "2026-03-02T00:00:00Z",
                    "updated_at": "2026-03-02T00:00:00Z",
                },
            ]
            result = await view_mcp.call(
                "list_views",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["name"] == "Overdue Tasks"
        assert result["data"][1]["query_data"] == {"priority": ["high", "urgent"]}

    async def test_empty_views(self, view_mcp):
        with patch("tools.views.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = await view_mcp.call(
                "list_views",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )
        assert result["ok"] is True
        assert result["data"] == []


class TestCreateView:
    async def test_creates_view(self, view_mcp):
        with patch("tools.views.api_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "view-new"}
            result = await view_mcp.call(
                "create_view",
                workspace_slug="test-workspace",
                project_id="proj-1",
                name="Sprint Board",
                description="Current sprint items",
                query_data={"state__group": ["started"]},
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "view-new"
        assert result["data"]["name"] == "Sprint Board"
        assert result["data"]["description"] == "Current sprint items"
        # Verify POST data
        call_args = mock_post.call_args
        post_data = call_args[0][1]
        assert post_data["name"] == "Sprint Board"
        assert post_data["description"] == "Current sprint items"
        assert post_data["query_data"] == {"state__group": ["started"]}

    async def test_creates_view_minimal(self, view_mcp):
        with patch("tools.views.api_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "view-min"}
            result = await view_mcp.call(
                "create_view",
                workspace_slug="test-workspace",
                project_id="proj-1",
                name="Quick View",
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "view-min"
        assert result["data"]["description"] == ""
        # No description or query_data in POST body
        call_args = mock_post.call_args
        post_data = call_args[0][1]
        assert "description" not in post_data
        assert "query_data" not in post_data

    async def test_rejects_cross_domain_view(self, view_mcp):
        result = await view_mcp.call(
            "create_view",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="Foreign View",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]


class TestGetView:
    async def test_retrieves_view(self, view_mcp):
        with patch("tools.views.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "id": "view-1",
                "name": "My View",
                "description": "A useful filter",
                "query_data": {"priority": ["high"]},
                "display_filters": {"layout": "list"},
                "display_properties": {},
                "access": 0,
                "is_locked": False,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-05T00:00:00Z",
            }
            result = await view_mcp.call(
                "get_view",
                workspace_slug="test-workspace",
                project_id="proj-1",
                view_id="view-1",
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "view-1"
        assert result["data"]["name"] == "My View"
        assert result["data"]["query_data"] == {"priority": ["high"]}
        assert result["data"]["display_filters"] == {"layout": "list"}
        assert result["data"]["is_locked"] is False


class TestUpdateView:
    async def test_rejects_cross_domain_update(self, view_mcp):
        result = await view_mcp.call(
            "update_view",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            view_id="view-1",
            name="Updated",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_updates_view(self, view_mcp):
        with patch("tools.views.api_patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = {
                "id": "view-1",
                "name": "Renamed View",
                "updated_at": "2026-03-10T00:00:00Z",
            }
            result = await view_mcp.call(
                "update_view",
                workspace_slug="test-workspace",
                project_id="proj-1",
                view_id="view-1",
                name="Renamed View",
                query_data={"state": ["done"]},
            )
        assert result["ok"] is True
        assert result["data"]["name"] == "Renamed View"
        # Verify PATCH data
        call_args = mock_patch.call_args
        patch_data = call_args[0][1]
        assert patch_data["name"] == "Renamed View"
        assert patch_data["query_data"] == {"state": ["done"]}

    async def test_rejects_empty_update(self, view_mcp):
        result = await view_mcp.call(
            "update_view",
            workspace_slug="test-workspace",
            project_id="proj-1",
            view_id="view-1",
        )
        assert result["ok"] is False
        assert "At least one" in result["error"]


class TestDeleteView:
    async def test_rejects_cross_domain_delete(self, view_mcp):
        result = await view_mcp.call(
            "delete_view",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            view_id="view-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_deletes_view(self, view_mcp):
        with patch("tools.views.api_delete", new_callable=AsyncMock) as mock_delete:
            result = await view_mcp.call(
                "delete_view",
                workspace_slug="test-workspace",
                project_id="proj-1",
                view_id="view-1",
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "view-1"
        assert result["data"]["status"] == "deleted"
        # Verify delete path
        call_args = mock_delete.call_args
        path = call_args[0][0]
        assert "/views/view-1/" in path
