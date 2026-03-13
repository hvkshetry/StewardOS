"""DI-based tests for plane-mcp coordination tools."""

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def coord_mcp(fake_mcp, get_client, mock_client):
    from tools.coordination import register_coordination_tools
    register_coordination_tools(fake_mcp, get_client)
    return fake_mcp


class TestListProjectMembers:
    async def test_returns_members(self, coord_mcp, mock_client):
        mock_client.projects.set_canned("get_members", [
            {
                "id": "user-1",
                "display_name": "Alice",
                "email": "alice@example.com",
                "role": 20,
            },
            {
                "id": "user-2",
                "display_name": "Bob",
                "email": "bob@example.com",
                "role": 15,
            },
        ])
        result = await coord_mcp.call(
            "list_project_members",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["display_name"] == "Alice"
        assert result["data"][1]["email"] == "bob@example.com"


class TestListWorkspaceMembers:
    async def test_returns_workspace_members(self, coord_mcp, mock_client):
        mock_client.workspaces.set_canned("get_members", [
            {
                "id": "user-1",
                "display_name": "Admin",
                "email": "admin@example.com",
                "role": 20,
            },
        ])
        result = await coord_mcp.call(
            "list_workspace_members",
            workspace_slug="test-workspace",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["display_name"] == "Admin"


class TestSearchWorkItems:
    async def test_returns_search_results(self, coord_mcp, mock_client):
        # SDK returns WorkItemSearch with .issues, but mock returns dict
        # Code falls back to normalize_list for dict inputs
        mock_client.work_items.set_canned("search", {
            "results": [
                {
                    "id": "wi-match-1",
                    "name": "Tax preparation 2026",
                    "project_id": "proj-1",
                    "state": "state-ip",
                    "priority": 3,
                },
            ],
        })
        result = await coord_mcp.call(
            "search_work_items",
            workspace_slug="test-workspace",
            query="tax preparation",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Tax preparation 2026"

    async def test_empty_search(self, coord_mcp, mock_client):
        mock_client.work_items.set_canned("search", {"results": []})
        result = await coord_mcp.call(
            "search_work_items",
            workspace_slug="test-workspace",
            query="nonexistent",
        )
        assert result["ok"] is True
        assert result["data"] == []


class TestListIntakeItems:
    async def test_returns_intake_items_with_issue_detail(self, coord_mcp, mock_client):
        # SDK IntakeWorkItem nests work-item data under issue_detail
        mock_client.intake.set_canned("list", [
            {
                "id": "intake-1",
                "issue": "issue-1",
                "issue_detail": {
                    "name": "New insurance inquiry",
                    "description_html": "<p>Client email about coverage</p>",
                    "priority": 2,
                },
                "source": "email",
                "status": -2,
                "created_at": "2026-03-09T10:00:00Z",
            },
        ])
        result = await coord_mcp.call(
            "list_intake_items",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "New insurance inquiry"
        assert result["data"][0]["source"] == "email"
        assert result["data"][0]["issue_id"] == "issue-1"

    async def test_returns_intake_items_flat_fallback(self, coord_mcp, mock_client):
        # Flat dict fallback (no issue_detail)
        mock_client.intake.set_canned("list", [
            {
                "id": "intake-2",
                "name": "Direct item",
                "description_html": "<p>desc</p>",
                "priority": 1,
                "source": "agent",
                "status": 0,
                "created_at": "2026-03-10T10:00:00Z",
            },
        ])
        result = await coord_mcp.call(
            "list_intake_items",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["name"] == "Direct item"


class TestCreateIntakeItem:
    async def test_rejects_cross_domain_intake(self, coord_mcp):
        result = await coord_mcp.call(
            "create_intake_item",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            title="Foreign item",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_creates_intake_item(self, coord_mcp, mock_client):
        mock_client.intake.set_canned("create", {"id": "intake-new", "issue": "wi-underlying"})
        result = await coord_mcp.call(
            "create_intake_item",
            workspace_slug="test-workspace",
            project_id="proj-1",
            title="Review policy renewal",
            description="Annual renewal notice received",
            priority="high",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "intake-new"
        assert result["data"]["issue_id"] == "wi-underlying"
        assert result["data"]["name"] == "Review policy renewal"
        assert result["data"]["priority"] == "high"

        # Verify SDK model was used
        calls = mock_client.intake._calls
        assert len(calls) == 1
        assert calls[0][0] == "create"
        create_data = calls[0][1]["data"]
        assert create_data.issue.name == "Review policy renewal"
        assert create_data.issue.priority == "high"


class TestUpdateIntakeItem:
    async def test_rejects_cross_domain_update(self, coord_mcp):
        result = await coord_mcp.call(
            "update_intake_item",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            work_item_id="intake-1",
            status="accepted",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_updates_intake_item(self, coord_mcp, mock_client):
        mock_client.intake.set_canned("update", {"id": "intake-1"})
        result = await coord_mcp.call(
            "update_intake_item",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="intake-1",
            status="accepted",
        )
        assert result["ok"] is True
        assert result["data"]["status"] == "accepted"

        # Verify status was mapped to integer
        calls = mock_client.intake._calls
        assert calls[0][1]["data"].status == 1  # accepted = 1

    async def test_rejects_empty_update(self, coord_mcp, mock_client):
        result = await coord_mcp.call(
            "update_intake_item",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="intake-1",
        )
        assert result["ok"] is False

    async def test_rejects_invalid_status(self, coord_mcp, mock_client):
        result = await coord_mcp.call(
            "update_intake_item",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="intake-1",
            status="invalid",
        )
        assert result["ok"] is False
        assert "Invalid status" in result["error"]


class TestGetWorkItemHistory:
    async def test_returns_activities(self, coord_mcp, mock_client):
        mock_client.work_items.activities.set_canned("list", [
            {
                "id": "act-1",
                "verb": "updated",
                "field": "state",
                "old_value": "Backlog",
                "new_value": "In Progress",
                "actor": "user-1",
                "created_at": "2026-03-05T09:00:00Z",
            },
            {
                "id": "act-2",
                "verb": "updated",
                "field": "priority",
                "old_value": "2",
                "new_value": "3",
                "actor": "user-1",
                "created_at": "2026-03-06T14:00:00Z",
            },
        ])
        result = await coord_mcp.call(
            "get_work_item_history",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["field"] == "state"
        assert result["data"][0]["new_value"] == "In Progress"
        assert result["data"][1]["field"] == "priority"
