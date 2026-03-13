"""DI-based tests for plane-mcp estimate tools."""

from unittest.mock import AsyncMock, patch

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def estimate_mcp(fake_mcp, get_client, mock_client):
    from tools.estimates import register_estimate_tools
    register_estimate_tools(fake_mcp, get_client)
    return fake_mcp


class TestListEstimates:
    async def test_returns_estimates(self, estimate_mcp):
        with patch("tools.estimates.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {
                    "id": "est-1",
                    "name": "Story Points",
                    "description": "Fibonacci scale",
                    "type": "points",
                    "last_used": True,
                    "points": [
                        {"id": "p-1", "key": 0, "value": "1"},
                        {"id": "p-2", "key": 1, "value": "2"},
                        {"id": "p-3", "key": 2, "value": "3"},
                        {"id": "p-4", "key": 3, "value": "5"},
                    ],
                },
            ]
            result = await estimate_mcp.call(
                "list_estimates",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Story Points"
        assert result["data"][0]["type"] == "points"
        assert len(result["data"][0]["points"]) == 4
        assert result["data"][0]["points"][0]["value"] == "1"
        assert result["data"][0]["points"][3]["value"] == "5"

    async def test_empty_estimates(self, estimate_mcp):
        with patch("tools.estimates.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = await estimate_mcp.call(
                "list_estimates",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )
        assert result["ok"] is True
        assert result["data"] == []


class TestCreateEstimate:
    async def test_creates_estimate(self, estimate_mcp):
        with patch("tools.estimates.api_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {
                "id": "est-new",
                "name": "T-Shirt Sizes",
                "type": "categories",
                "points": [
                    {"id": "p-1", "key": 0, "value": "XS"},
                    {"id": "p-2", "key": 1, "value": "S"},
                    {"id": "p-3", "key": 2, "value": "M"},
                    {"id": "p-4", "key": 3, "value": "L"},
                    {"id": "p-5", "key": 4, "value": "XL"},
                ],
            }
            result = await estimate_mcp.call(
                "create_estimate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                name="T-Shirt Sizes",
                estimate_type="categories",
                estimate_points=[
                    {"key": 0, "value": "XS"},
                    {"key": 1, "value": "S"},
                    {"key": 2, "value": "M"},
                    {"key": 3, "value": "L"},
                    {"key": 4, "value": "XL"},
                ],
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "est-new"
        assert result["data"]["name"] == "T-Shirt Sizes"
        assert result["data"]["type"] == "categories"
        assert result["data"]["points_count"] == 5
        # Verify POST data structure
        call_args = mock_post.call_args
        post_data = call_args[0][1]
        assert post_data["estimate"]["name"] == "T-Shirt Sizes"
        assert post_data["estimate"]["type"] == "categories"
        assert len(post_data["estimate_points"]) == 5

    async def test_creates_estimate_minimal(self, estimate_mcp):
        with patch("tools.estimates.api_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "est-min", "points": []}
            result = await estimate_mcp.call(
                "create_estimate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                name="Quick Estimate",
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "est-min"
        assert result["data"]["type"] == "categories"
        assert result["data"]["points_count"] == 0

    async def test_rejects_cross_domain_estimate(self, estimate_mcp):
        result = await estimate_mcp.call(
            "create_estimate",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="Foreign Estimate",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]


class TestGetEstimate:
    async def test_retrieves_estimate(self, estimate_mcp):
        with patch("tools.estimates.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "id": "est-1",
                "name": "Story Points",
                "description": "Fibonacci scale",
                "type": "points",
                "last_used": True,
                "points": [
                    {"id": "p-1", "key": 0, "value": "1"},
                    {"id": "p-2", "key": 1, "value": "2"},
                    {"id": "p-3", "key": 2, "value": "3"},
                ],
            }
            result = await estimate_mcp.call(
                "get_estimate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                estimate_id="est-1",
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "est-1"
        assert result["data"]["name"] == "Story Points"
        assert result["data"]["type"] == "points"
        assert result["data"]["last_used"] is True
        assert len(result["data"]["points"]) == 3


class TestUpdateEstimate:
    async def test_rejects_cross_domain_update(self, estimate_mcp):
        result = await estimate_mcp.call(
            "update_estimate",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            estimate_id="est-1",
            name="Updated",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_updates_estimate(self, estimate_mcp):
        with patch("tools.estimates.api_patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = {
                "id": "est-1",
                "name": "Renamed Points",
                "type": "points",
            }
            result = await estimate_mcp.call(
                "update_estimate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                estimate_id="est-1",
                name="Renamed Points",
                estimate_points=[
                    {"id": "p-1", "key": 0, "value": "1"},
                    {"id": "p-2", "key": 1, "value": "3"},
                ],
            )
        assert result["ok"] is True
        assert result["data"]["name"] == "Renamed Points"
        # Verify PATCH data
        call_args = mock_patch.call_args
        patch_data = call_args[0][1]
        assert patch_data["estimate"]["name"] == "Renamed Points"
        assert len(patch_data["estimate_points"]) == 2

    async def test_rejects_empty_update(self, estimate_mcp):
        result = await estimate_mcp.call(
            "update_estimate",
            workspace_slug="test-workspace",
            project_id="proj-1",
            estimate_id="est-1",
        )
        assert result["ok"] is False
        assert "At least one" in result["error"]


class TestDeleteEstimate:
    async def test_rejects_cross_domain_delete(self, estimate_mcp):
        result = await estimate_mcp.call(
            "delete_estimate",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            estimate_id="est-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_deletes_estimate(self, estimate_mcp):
        with patch("tools.estimates.api_delete", new_callable=AsyncMock) as mock_delete:
            result = await estimate_mcp.call(
                "delete_estimate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                estimate_id="est-1",
            )
        assert result["ok"] is True
        assert result["data"]["id"] == "est-1"
        assert result["data"]["status"] == "deleted"
        # Verify delete path
        call_args = mock_delete.call_args
        path = call_args[0][0]
        assert "/estimates/est-1/" in path
