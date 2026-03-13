"""DI-based tests for plane-mcp project tools."""

import os

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def project_mcp(fake_mcp, get_client, mock_client):
    from tools.projects import register_project_tools
    register_project_tools(fake_mcp, get_client)
    return fake_mcp


class TestCreateProject:
    async def test_create_project_in_home_workspace(self, project_mcp, mock_client):
        mock_client.configure_projects(
            list_data=[{"id": f"proj-{i}"} for i in range(3)],
            create_data={
                "id": "proj-new-1",
                "identifier": "NP1",
            },
        )
        result = await project_mcp.call(
            "create_project",
            workspace_slug="test-workspace",
            name="My Project",
            description="A new project",
            network=2,
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "proj-new-1"
        assert result["data"]["identifier"] == "NP1"
        assert result["data"]["name"] == "My Project"
        assert result["data"]["description"] == "A new project"
        assert result["data"]["network"] == 2
        assert result["data"]["cross_domain"] is False
        assert "warnings" not in result

    async def test_create_project_cross_domain_rejected(self, project_mcp, mock_client):
        """Cross-domain project creation is rejected for governance."""
        result = await project_mcp.call(
            "create_project",
            workspace_slug="other-workspace",
            name="Cross-domain Project",
        )
        assert result["ok"] is False
        assert "error" in result
        assert "other-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_create_project_sprawl_warning_over_20(self, project_mcp, mock_client):
        mock_client.configure_projects(
            list_data=[{"id": f"proj-{i}"} for i in range(25)],
            create_data={
                "id": "proj-sprawl-1",
                "identifier": "SP1",
            },
        )
        result = await project_mcp.call(
            "create_project",
            workspace_slug="test-workspace",
            name="Sprawl Project",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "proj-sprawl-1"
        assert "warnings" in result
        assert any("25 projects" in w for w in result["warnings"])
        assert any("archiving" in w.lower() for w in result["warnings"])

    async def test_create_project_empty_home_workspace_no_governance(
        self, project_mcp, mock_client, monkeypatch,
    ):
        """When PLANE_HOME_WORKSPACE is empty, governance check is skipped."""
        monkeypatch.setenv("PLANE_HOME_WORKSPACE", "")
        mock_client.configure_projects(
            list_data=[],
            create_data={
                "id": "proj-nogov-1",
                "identifier": "NG1",
            },
        )
        result = await project_mcp.call(
            "create_project",
            workspace_slug="any-workspace",
            name="Ungoverned Project",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "proj-nogov-1"
        assert result["data"]["cross_domain"] is False
        assert "warnings" not in result


class TestGetProject:
    async def test_get_project_returns_details(self, project_mcp, mock_client):
        mock_client.configure_projects(
            retrieve_data={
                "id": "proj-42",
                "name": "Test Project",
                "identifier": "TP",
                "description": "A test project",
                "network": 2,
                "total_members": 5,
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-06-15T12:00:00Z",
            },
        )
        result = await project_mcp.call(
            "get_project",
            workspace_slug="test-workspace",
            project_id="proj-42",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "proj-42"
        assert result["data"]["name"] == "Test Project"
        assert result["data"]["identifier"] == "TP"
        assert result["data"]["description"] == "A test project"
        assert result["data"]["network"] == 2
        assert result["data"]["member_count"] == 5
        assert result["data"]["created_at"] == "2025-01-01T00:00:00Z"
        assert result["data"]["updated_at"] == "2025-06-15T12:00:00Z"
