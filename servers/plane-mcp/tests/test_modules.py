"""DI-based tests for plane-mcp module tools."""

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def module_mcp(fake_mcp, get_client, mock_client):
    from tools.modules import register_module_tools
    register_module_tools(fake_mcp, get_client)
    return fake_mcp


class TestListModules:
    async def test_returns_modules(self, module_mcp, mock_client):
        mock_client.configure_modules(list_data=[
            {
                "id": "mod-1",
                "name": "Tax Season 2026",
                "description": "All tax-related work",
                "start_date": "2026-01-15",
                "target_date": "2026-04-15",
                "status": "active",
                "created_at": "2026-01-10T00:00:00Z",
            },
        ])
        result = await module_mcp.call(
            "list_modules",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Tax Season 2026"
        assert result["data"][0]["target_date"] == "2026-04-15"

    async def test_empty_modules(self, module_mcp, mock_client):
        mock_client.configure_modules(list_data=[])
        result = await module_mcp.call(
            "list_modules",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert result["data"] == []


class TestCreateModule:
    async def test_creates_module(self, module_mcp, mock_client):
        mock_client.configure_modules(create_data={"id": "mod-new"})
        result = await module_mcp.call(
            "create_module",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="Estate Planning",
            description="Succession and trust updates",
            start_date="2026-02-01",
            target_date="2026-06-30",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "mod-new"
        assert result["data"]["name"] == "Estate Planning"
        assert result["data"]["target_date"] == "2026-06-30"

    async def test_rejects_cross_domain_module(self, module_mcp, mock_client):
        result = await module_mcp.call(
            "create_module",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="Foreign module",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_creates_module_minimal(self, module_mcp, mock_client):
        mock_client.configure_modules(create_data={"id": "mod-min"})
        result = await module_mcp.call(
            "create_module",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="Quick module",
        )
        assert result["ok"] is True
        assert result["data"]["description"] == ""
        assert result["data"]["start_date"] == ""


class TestAddModuleWorkItems:
    async def test_rejects_cross_domain_add(self, module_mcp):
        result = await module_mcp.call(
            "add_module_work_items",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            module_id="mod-1",
            work_item_ids=["wi-1"],
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_adds_work_items(self, module_mcp, mock_client):
        result = await module_mcp.call(
            "add_module_work_items",
            workspace_slug="test-workspace",
            project_id="proj-1",
            module_id="mod-1",
            work_item_ids=["wi-1", "wi-2"],
        )
        assert result["ok"] is True
        assert result["data"]["module_id"] == "mod-1"
        assert result["data"]["added_count"] == 2
        # Verify SDK call
        calls = mock_client.modules._calls
        add_calls = [c for c in calls if c[0] == "add_work_items"]
        assert len(add_calls) == 1
        assert add_calls[0][1]["issue_ids"] == ["wi-1", "wi-2"]


class TestRemoveModuleWorkItem:
    async def test_rejects_cross_domain_remove(self, module_mcp):
        result = await module_mcp.call(
            "remove_module_work_item",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            module_id="mod-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_removes_work_item(self, module_mcp, mock_client):
        result = await module_mcp.call(
            "remove_module_work_item",
            workspace_slug="test-workspace",
            project_id="proj-1",
            module_id="mod-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is True
        assert result["data"]["module_id"] == "mod-1"
        assert result["data"]["removed_work_item_id"] == "wi-1"
