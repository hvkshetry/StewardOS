"""Tests for canonical Plane project_admin tool."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def project_admin_mcp(fake_mcp, get_client):
    from tools.project_admin import register_project_admin_tools

    register_project_admin_tools(fake_mcp, get_client)
    return fake_mcp


class TestProjectAdminProjectAndStateOps:
    async def test_creates_project(self, project_admin_mcp, mock_client):
        mock_client.configure_projects(
            create_data={
                "id": "proj-new",
                "name": "Family Office Ops",
                "identifier": "OPS",
                "description": "Operations board",
                "network": 2,
            }
        )

        result = await project_admin_mcp.call(
            "project_admin",
            operation="create_project",
            workspace_slug="test-workspace",
            name="Family Office Ops",
            description="Operations board",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "proj-new"
        assert result["data"]["identifier"] == "OPS"

    async def test_updates_state(self, project_admin_mcp, mock_client):
        mock_client.states.set_canned(
            "update",
            {"id": "state-1", "name": "In Review", "group": "started", "color": "#123456"},
        )

        result = await project_admin_mcp.call(
            "project_admin",
            operation="update_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            state_id="state-1",
            name="In Review",
            color="#123456",
        )

        assert result["ok"] is True
        assert result["data"]["id"] == "state-1"
        assert result["data"]["name"] == "In Review"


class TestProjectAdminHttpBackedOps:
    async def test_lists_views(self, project_admin_mcp):
        with patch("tools.project_admin.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {"id": "view-1", "name": "Inbox", "description": "triage", "query_data": {"state": ["todo"]}},
            ]
            result = await project_admin_mcp.call(
                "project_admin",
                operation="list_views",
                workspace_slug="test-workspace",
                project_id="proj-1",
            )

        assert result["ok"] is True
        assert result["data"][0]["id"] == "view-1"
        assert mock_get.call_args.args[0] == "/workspaces/test-workspace/projects/proj-1/views/"

    async def test_deletes_estimate(self, project_admin_mcp):
        with patch("tools.project_admin.api_delete", new_callable=AsyncMock) as mock_delete:
            result = await project_admin_mcp.call(
                "project_admin",
                operation="delete_estimate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                estimate_id="est-1",
            )

        assert result["ok"] is True
        assert result["data"]["status"] == "deleted"
        assert mock_delete.call_args.args[0] == "/workspaces/test-workspace/projects/proj-1/estimates/est-1/"
