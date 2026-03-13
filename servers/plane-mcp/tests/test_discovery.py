"""DI-based tests for plane-mcp discovery tools."""

from unittest.mock import AsyncMock, patch

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def discovery_mcp(fake_mcp, get_client, mock_client):
    from tools.discovery import register_discovery_tools
    register_discovery_tools(fake_mcp, get_client)
    return fake_mcp


class TestListWorkspaces:
    @patch("tools.discovery.api_get", new_callable=AsyncMock)
    async def test_returns_workspaces(self, mock_api_get, discovery_mcp):
        mock_api_get.return_value = [
            {
                "slug": "chief-of-staff",
                "name": "Chief of Staff",
                "total_members": 3,
                "id": "ws-1",
            },
            {
                "slug": "investment-office",
                "name": "Investment Office",
                "total_members": 2,
                "id": "ws-2",
            },
        ]
        result = await discovery_mcp.call("list_workspaces")
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["slug"] == "chief-of-staff"
        assert result["data"][1]["member_count"] == 2

    @patch("tools.discovery.api_get", new_callable=AsyncMock)
    async def test_handles_empty_workspaces(self, mock_api_get, discovery_mcp):
        mock_api_get.return_value = []
        result = await discovery_mcp.call("list_workspaces")
        assert result["ok"] is True
        assert result["data"] == []


class TestListProjects:
    async def test_returns_projects(self, discovery_mcp, mock_client):
        mock_client.configure_projects(list_data=[
            {
                "id": "proj-1",
                "name": "Insurance Operations",
                "identifier": "INS",
                "description": "Insurance workspace",
                "network": 2,
                "total_members": 3,
            },
        ])
        result = await discovery_mcp.call(
            "list_projects",
            workspace_slug="test-workspace",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["identifier"] == "INS"

    async def test_handles_empty_project_list(self, discovery_mcp, mock_client):
        mock_client.configure_projects(list_data=[])
        result = await discovery_mcp.call(
            "list_projects",
            workspace_slug="test-workspace",
        )
        assert result["ok"] is True
        assert result["data"] == []


class TestGetProjectBundle:
    async def test_returns_full_bundle(self, discovery_mcp, mock_client):
        mock_client.configure_projects(
            retrieve_data={
                "id": "proj-1",
                "name": "Test Project",
                "identifier": "TP",
                "description": "desc",
                "network": 2,
            },
        )
        mock_client.configure_states(list_data=[
            {"id": "state-1", "name": "Backlog", "group": "backlog", "color": "#gray"},
        ])
        mock_client.configure_labels(list_data=[
            {"id": "lbl-1", "name": "case", "color": "#blue"},
        ])
        mock_client.configure_work_items(list_data=[
            {
                "id": "wi-1",
                "name": "Test Item",
                "state": "state-1",
                "priority": 2,
                "labels": [],
                "parent": None,
                "created_at": "2026-03-01T00:00:00Z",
            },
        ])
        result = await discovery_mcp.call(
            "get_project_bundle",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert result["data"]["project"]["name"] == "Test Project"
        assert len(result["data"]["states"]) == 1
        assert len(result["data"]["labels"]) == 1
        assert len(result["data"]["recent_work_items"]) == 1


class TestGetCaseBundle:
    async def test_returns_case_with_children(self, discovery_mcp, mock_client):
        mock_client.configure_work_items(
            retrieve_data={
                "id": "case-1",
                "name": "Case One",
                "description_html": "",
                "state": "state-1",
                "priority": 2,
                "labels": [],
                "parent": None,
                "assignees": [],
                "start_date": None,
                "target_date": None,
                "created_at": "2026-03-01",
                "updated_at": "2026-03-01",
            },
            list_data=[
                {
                    "id": "wi-child",
                    "name": "Child Task",
                    "description_html": "",
                    "state": "state-1",
                    "priority": 2,
                    "labels": [],
                    "parent": "case-1",
                    "assignees": [],
                    "start_date": None,
                    "target_date": None,
                    "created_at": "2026-03-01",
                    "updated_at": "2026-03-01",
                },
            ],
        )
        mock_client.work_items.comments.set_canned("list", [])
        result = await discovery_mcp.call(
            "get_case_bundle",
            workspace_slug="test-workspace",
            project_id="proj-1",
            case_id="case-1",
        )
        assert result["ok"] is True
        assert result["data"]["case"]["id"] == "case-1"
        assert len(result["data"]["child_work_items"]) == 1
        assert result["data"]["child_work_items"][0]["name"] == "Child Task"


class TestGetTaskBundle:
    async def test_returns_task_with_sub_items(self, discovery_mcp, mock_client):
        mock_client.configure_work_items(
            retrieve_data={
                "id": "task-1",
                "name": "Main Task",
                "description_html": "",
                "state": "state-1",
                "priority": 2,
                "labels": [],
                "parent": "case-1",
                "assignees": [],
                "start_date": None,
                "target_date": None,
                "created_at": "2026-03-01",
                "updated_at": "2026-03-01",
            },
            list_data=[
                {
                    "id": "sub-1",
                    "name": "Sub Task",
                    "description_html": "",
                    "state": "state-1",
                    "priority": 1,
                    "labels": [],
                    "parent": "task-1",
                    "assignees": [],
                    "start_date": None,
                    "target_date": None,
                    "created_at": "2026-03-01",
                    "updated_at": "2026-03-01",
                },
            ],
        )
        mock_client.work_items.comments.set_canned("list", [])
        result = await discovery_mcp.call(
            "get_task_bundle",
            workspace_slug="test-workspace",
            project_id="proj-1",
            task_id="task-1",
        )
        assert result["ok"] is True
        assert result["data"]["task"]["id"] == "task-1"
        assert len(result["data"]["sub_items"]) == 1


class TestListOverdueTasks:
    async def test_finds_overdue_items(self, discovery_mcp, mock_client):
        mock_client.configure_states(list_data=[
            {"id": "state-1", "name": "Backlog", "group": "backlog"},
            {"id": "state-2", "name": "Done", "group": "completed"},
        ])
        mock_client.configure_work_items(list_data=[
            {
                "id": "wi-overdue",
                "name": "Overdue Task",
                "description_html": "",
                "state": "state-1",
                "priority": 2,
                "labels": [],
                "parent": None,
                "assignees": [],
                "start_date": None,
                "target_date": "2020-01-01",
                "created_at": "2020-01-01",
                "updated_at": "2020-01-01",
            },
            {
                "id": "wi-done",
                "name": "Done Task",
                "description_html": "",
                "state": "state-2",
                "priority": 2,
                "labels": [],
                "parent": None,
                "assignees": [],
                "start_date": None,
                "target_date": "2020-01-01",
                "created_at": "2020-01-01",
                "updated_at": "2020-01-01",
            },
            {
                "id": "wi-no-date",
                "name": "No Date Task",
                "description_html": "",
                "state": "state-1",
                "priority": 2,
                "labels": [],
                "parent": None,
                "assignees": [],
                "start_date": None,
                "target_date": None,
                "created_at": "2020-01-01",
                "updated_at": "2020-01-01",
            },
        ])
        result = await discovery_mcp.call(
            "list_overdue_tasks",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "wi-overdue"
