"""DI-based tests for plane-mcp creation tools."""

import os

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def creation_mcp(fake_mcp, get_client, mock_client):
    from tools.creation import register_creation_tools
    register_creation_tools(fake_mcp, get_client)
    return fake_mcp


class TestCreateCase:
    async def test_creates_case_in_home_workspace(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[{"id": "lbl-1", "name": "case"}],
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-new-1", "name": "New case"},
        )
        result = await creation_mcp.call(
            "create_case",
            workspace_slug="test-workspace",
            project_id="proj-1",
            title="New case",
            description="Case description",
            priority="high",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "wi-new-1"
        assert result["data"]["cross_domain"] is False
        assert "case" in result["data"]["labels"]

    async def test_creates_case_with_additional_labels(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[],
            create_data={"id": "lbl-new", "name": "case"},
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-new-2", "name": "Tagged case"},
        )
        result = await creation_mcp.call(
            "create_case",
            workspace_slug="test-workspace",
            project_id="proj-1",
            title="Tagged case",
            labels=["urgent-review"],
        )
        assert result["ok"] is True
        assert "case" in result["data"]["labels"]
        assert "urgent-review" in result["data"]["labels"]

    async def test_cross_domain_case_is_rejected(self, creation_mcp, mock_client):
        result = await creation_mcp.call(
            "create_case",
            workspace_slug="other-workspace",
            project_id="proj-1",
            title="Cross-domain case",
        )
        assert result["ok"] is False
        assert "other-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_priority_mapping(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[{"id": "lbl-1", "name": "case"}],
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-p1", "name": "Urgent case"},
        )
        result = await creation_mcp.call(
            "create_case",
            workspace_slug="test-workspace",
            project_id="proj-1",
            title="Urgent case",
            priority="urgent",
        )
        assert result["ok"] is True
        assert result["data"]["priority"] == "urgent"


class TestCreateAgentTask:
    async def test_creates_agent_task(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[],
            create_data={"id": "lbl-at", "name": "agent-task"},
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-at-1", "name": "Agent task"},
        )
        result = await creation_mcp.call(
            "create_agent_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="Agent task",
            target_alias="comptroller",
            priority="medium",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "wi-at-1"
        assert result["data"]["parent"] == "case-1"
        assert result["data"]["target_alias"] == "comptroller"
        assert "agent-task" in result["data"]["labels"]
        assert "target_alias:comptroller" in result["data"]["labels"]
        assert "delegated_by:case-1" in result["data"]["labels"]

    async def test_agent_task_cross_domain_rejected(self, creation_mcp, mock_client):
        result = await creation_mcp.call(
            "create_agent_task",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="Delegated task",
            target_alias="estate-counsel",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]


class TestCreateHumanTask:
    async def test_creates_human_task(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[],
            create_data={"id": "lbl-ht", "name": "human-task"},
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-ht-1", "name": "Human task"},
        )
        result = await creation_mcp.call(
            "create_human_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="Human task",
            description="Review document manually",
            assignee_id="user-42",
            priority="low",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "wi-ht-1"
        assert result["data"]["parent"] == "case-1"
        assert result["data"]["assignee_id"] == "user-42"
        assert "human-task" in result["data"]["labels"]
        assert "delegated_by:case-1" in result["data"]["labels"]
        assert result["data"]["cross_domain"] is False

    async def test_human_task_without_assignee(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[{"id": "lbl-ht", "name": "human-task"}],
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-ht-2", "name": "Unassigned task"},
        )
        result = await creation_mcp.call(
            "create_human_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="Unassigned task",
        )
        assert result["ok"] is True
        assert result["data"]["assignee_id"] == ""

    async def test_human_task_with_due_date(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[{"id": "lbl-ht", "name": "human-task"}],
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-ht-3", "name": "Dated task"},
        )
        result = await creation_mcp.call(
            "create_human_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="Dated task",
            due_date="2026-04-15",
            start_date="2026-03-01",
        )
        assert result["ok"] is True
        assert result["data"]["due_date"] == "2026-04-15"
        assert result["data"]["start_date"] == "2026-03-01"
        # Verify the data passed to the SDK
        calls = mock_client.work_items._calls
        create_call = [c for c in calls if c[0] == "create"]
        assert len(create_call) == 1
        create_data = create_call[0][1]["data"]
        assert create_data.target_date == "2026-04-15"
        assert create_data.start_date == "2026-03-01"

    async def test_human_task_cross_domain_rejected(self, creation_mcp, mock_client):
        result = await creation_mcp.call(
            "create_human_task",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="Cross-domain human task",
            assignee_id="user-42",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_human_task_without_dates(self, creation_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[{"id": "lbl-ht", "name": "human-task"}],
        )
        mock_client.configure_work_items(
            create_data={"id": "wi-ht-4", "name": "No-date task"},
        )
        result = await creation_mcp.call(
            "create_human_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            case_id="case-1",
            title="No-date task",
        )
        assert result["ok"] is True
        assert result["data"]["due_date"] == ""
        assert result["data"]["start_date"] == ""
        # Verify dates NOT in create data
        calls = mock_client.work_items._calls
        create_call = [c for c in calls if c[0] == "create"]
        create_data = create_call[0][1]["data"]
        assert create_data.target_date is None
        assert create_data.start_date is None
