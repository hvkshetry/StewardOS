"""DI-based tests for plane-mcp page tools."""

from unittest.mock import AsyncMock, patch

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def page_mcp(fake_mcp, get_client, mock_client):
    from tools.pages import register_page_tools
    register_page_tools(fake_mcp, get_client)
    return fake_mcp


class TestListProjectPages:
    async def test_returns_pages(self, page_mcp):
        with patch("tools.pages.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {
                    "id": "page-1",
                    "name": "Meeting Notes",
                    "owned_by": "user-1",
                    "access": 0,
                    "is_locked": False,
                    "archived_at": None,
                    "created_at": "2026-03-01T00:00:00Z",
                    "updated_at": "2026-03-05T00:00:00Z",
                },
            ]
            result = await page_mcp.call(
                "list_project_pages",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Meeting Notes"

    async def test_empty_pages(self, page_mcp):
        with patch("tools.pages.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = []
            result = await page_mcp.call(
                "list_project_pages",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )
        assert result["ok"] is True
        assert result["data"] == []


class TestCreateProjectPage:
    async def test_rejects_cross_domain_create(self, page_mcp):
        result = await page_mcp.call(
            "create_project_page",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="Foreign Page",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_creates_page(self, page_mcp, mock_client):
        mock_client.pages.set_canned(
            "create_project_page", {"id": "page-new", "name": "Test Page"},
        )
        result = await page_mcp.call(
            "create_project_page",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="Test Page",
            content_html="<p>Hello world</p>",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "page-new"
        assert result["data"]["name"] == "Test Page"
        # Verify SDK call
        calls = mock_client.pages._calls
        assert len(calls) == 1
        assert calls[0][0] == "create_project_page"
        assert calls[0][1]["data"].name == "Test Page"
        assert calls[0][1]["data"].description_html == "<p>Hello world</p>"


class TestGetProjectPage:
    async def test_retrieves_page(self, page_mcp, mock_client):
        mock_client.pages.set_canned("retrieve_project_page", {
            "id": "page-1",
            "name": "Notes",
            "description_html": "<p>Some content</p>",
            "owned_by": "user-1",
            "access": 0,
            "is_locked": False,
            "created_at": "2026-03-01T00:00:00Z",
            "updated_at": "2026-03-05T00:00:00Z",
        })
        result = await page_mcp.call(
            "get_project_page",
            workspace_slug="test-workspace",
            project_id="proj-1",
            page_id="page-1",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "page-1"
        assert result["data"]["name"] == "Notes"
        assert result["data"]["description_html"] == "<p>Some content</p>"


class TestUpdateProjectPage:
    async def test_rejects_cross_domain_update(self, page_mcp):
        result = await page_mcp.call(
            "update_project_page",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            page_id="page-1",
            name="Updated",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_updates_page(self, page_mcp):
        with patch("tools.pages.api_patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = {
                "id": "page-1",
                "name": "Updated Notes",
                "updated_at": "2026-03-10T00:00:00Z",
            }
            result = await page_mcp.call(
                "update_project_page",
                workspace_slug="test-workspace",
                project_id="proj-1",
                page_id="page-1",
                name="Updated Notes",
                content_html="<p>New content</p>",
            )
        assert result["ok"] is True
        assert result["data"]["name"] == "Updated Notes"
        # Verify patch data
        call_args = mock_patch.call_args
        patch_data = call_args[0][1]
        assert patch_data["name"] == "Updated Notes"
        assert patch_data["description_html"] == "<p>New content</p>"

    async def test_rejects_empty_update(self, page_mcp):
        result = await page_mcp.call(
            "update_project_page",
            workspace_slug="test-workspace",
            project_id="proj-1",
            page_id="page-1",
        )
        assert result["ok"] is False
        assert "At least one" in result["error"]


class TestArchiveProjectPage:
    async def test_rejects_cross_domain_archive(self, page_mcp):
        result = await page_mcp.call(
            "archive_project_page",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            page_id="page-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_archives_page(self, page_mcp):
        with patch("tools.pages.api_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {}
            result = await page_mcp.call(
                "archive_project_page",
                workspace_slug="test-workspace",
                project_id="proj-1",
                page_id="page-1",
            )
        assert result["ok"] is True
        assert result["data"]["status"] == "archived"
        # Verify archive path
        call_args = mock_post.call_args
        path = call_args[0][0]
        assert "/pages/page-1/archive/" in path


class TestDeleteProjectPage:
    async def test_rejects_cross_domain_delete(self, page_mcp):
        result = await page_mcp.call(
            "delete_project_page",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            page_id="page-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_deletes_page(self, page_mcp):
        with (
            patch("tools.pages.api_post", new_callable=AsyncMock) as mock_post,
            patch("tools.pages.api_delete", new_callable=AsyncMock) as mock_delete,
        ):
            mock_post.return_value = {}
            result = await page_mcp.call(
                "delete_project_page",
                workspace_slug="test-workspace",
                project_id="proj-1",
                page_id="page-1",
            )
        assert result["ok"] is True
        assert result["data"]["status"] == "deleted"
        # Should archive first, then delete
        mock_post.assert_called_once()
        mock_delete.assert_called_once()
