"""DI-based tests for plane-mcp cycle tools."""

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def cycle_mcp(fake_mcp, get_client, mock_client):
    from tools.cycles import register_cycle_tools
    register_cycle_tools(fake_mcp, get_client)
    return fake_mcp


class TestListCycles:
    async def test_returns_cycles(self, cycle_mcp, mock_client):
        mock_client.configure_cycles(list_data=[
            {
                "id": "cycle-1",
                "name": "Sprint 1",
                "description": "First sprint",
                "start_date": "2026-03-01",
                "end_date": "2026-03-14",
                "status": "current",
                "created_at": "2026-02-28T00:00:00Z",
            },
            {
                "id": "cycle-2",
                "name": "Sprint 2",
                "description": "",
                "start_date": "2026-03-15",
                "end_date": "2026-03-28",
                "status": "upcoming",
                "created_at": "2026-02-28T00:00:00Z",
            },
        ])
        result = await cycle_mcp.call(
            "list_cycles",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["name"] == "Sprint 1"
        assert result["data"][0]["status"] == "current"
        assert result["data"][1]["name"] == "Sprint 2"

    async def test_empty_cycles(self, cycle_mcp, mock_client):
        mock_client.configure_cycles(list_data=[])
        result = await cycle_mcp.call(
            "list_cycles",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert result["data"] == []


class TestCreateCycle:
    async def test_creates_cycle(self, cycle_mcp, mock_client):
        mock_client.configure_cycles(create_data={"id": "cycle-new"})
        result = await cycle_mcp.call(
            "create_cycle",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="Q1 Sprint",
            description="First quarter sprint",
            start_date="2026-01-01",
            end_date="2026-03-31",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "cycle-new"
        assert result["data"]["name"] == "Q1 Sprint"
        assert result["data"]["start_date"] == "2026-01-01"
        assert result["data"]["end_date"] == "2026-03-31"

    async def test_rejects_cross_domain_cycle(self, cycle_mcp, mock_client):
        result = await cycle_mcp.call(
            "create_cycle",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="Foreign cycle",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_creates_cycle_minimal(self, cycle_mcp, mock_client):
        mock_client.configure_cycles(create_data={"id": "cycle-min"})
        result = await cycle_mcp.call(
            "create_cycle",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="Quick cycle",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "cycle-min"
        assert result["data"]["description"] == ""


class TestAddCycleWorkItems:
    async def test_rejects_cross_domain_add(self, cycle_mcp):
        result = await cycle_mcp.call(
            "add_cycle_work_items",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            cycle_id="cycle-1",
            work_item_ids=["wi-1"],
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_adds_work_items(self, cycle_mcp, mock_client):
        result = await cycle_mcp.call(
            "add_cycle_work_items",
            workspace_slug="test-workspace",
            project_id="proj-1",
            cycle_id="cycle-1",
            work_item_ids=["wi-1", "wi-2", "wi-3"],
        )
        assert result["ok"] is True
        assert result["data"]["cycle_id"] == "cycle-1"
        assert result["data"]["added_count"] == 3
        # Verify SDK call
        calls = mock_client.cycles._calls
        add_calls = [c for c in calls if c[0] == "add_work_items"]
        assert len(add_calls) == 1
        assert add_calls[0][1]["issue_ids"] == ["wi-1", "wi-2", "wi-3"]


class TestRemoveCycleWorkItem:
    async def test_rejects_cross_domain_remove(self, cycle_mcp):
        result = await cycle_mcp.call(
            "remove_cycle_work_item",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            cycle_id="cycle-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_removes_work_item(self, cycle_mcp, mock_client):
        result = await cycle_mcp.call(
            "remove_cycle_work_item",
            workspace_slug="test-workspace",
            project_id="proj-1",
            cycle_id="cycle-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is True
        assert result["data"]["cycle_id"] == "cycle-1"
        assert result["data"]["removed_work_item_id"] == "wi-1"
        # Verify SDK call
        calls = mock_client.cycles._calls
        remove_calls = [c for c in calls if c[0] == "remove_work_item"]
        assert len(remove_calls) == 1


class TestGetCycleProgress:
    async def test_returns_progress(self, cycle_mcp, mock_client):
        mock_client.configure_cycles(retrieve_data={
            "id": "cycle-1",
            "name": "Sprint 1",
            "description": "First sprint",
            "start_date": "2026-03-01",
            "end_date": "2026-03-14",
            "status": "current",
        })
        mock_client.cycles.set_canned("list_work_items", [
            {
                "id": "wi-1",
                "name": "Task A",
                "description_html": "",
                "state": "state-done",
                "priority": 2,
                "labels": [],
                "parent": None,
                "assignees": [],
                "start_date": None,
                "target_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-05T00:00:00Z",
            },
            {
                "id": "wi-2",
                "name": "Task B",
                "description_html": "",
                "state": "state-ip",
                "priority": 3,
                "labels": [],
                "parent": None,
                "assignees": [],
                "start_date": None,
                "target_date": None,
                "created_at": "2026-03-01T00:00:00Z",
                "updated_at": "2026-03-10T00:00:00Z",
            },
        ])

        result = await cycle_mcp.call(
            "get_cycle_progress",
            workspace_slug="test-workspace",
            project_id="proj-1",
            cycle_id="cycle-1",
        )
        assert result["ok"] is True
        assert result["data"]["cycle"]["name"] == "Sprint 1"
        assert result["data"]["total_count"] == 2
        assert len(result["data"]["work_items"]) == 2
        assert result["data"]["work_items"][0]["name"] == "Task A"
        # Verify per-state progress summary
        assert result["data"]["by_state"] == {"state-done": 1, "state-ip": 1}
