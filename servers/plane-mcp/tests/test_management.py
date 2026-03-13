"""DI-based tests for plane-mcp management tools (states and labels)."""

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def mgmt_mcp(fake_mcp, get_client, mock_client):
    from tools.management import register_management_tools
    register_management_tools(fake_mcp, get_client)
    return fake_mcp


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class TestListStates:
    async def test_returns_states(self, mgmt_mcp, mock_client):
        mock_client.configure_states(list_data=[
            {"id": "s-1", "name": "Backlog", "group": "backlog", "color": "#ccc", "sequence": 1},
            {"id": "s-2", "name": "In Progress", "group": "started", "color": "#00f", "sequence": 2},
            {"id": "s-3", "name": "Done", "group": "completed", "color": "#0f0", "sequence": 3},
        ])
        result = await mgmt_mcp.call(
            "list_states",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 3
        assert result["data"][0]["name"] == "Backlog"
        assert result["data"][2]["group"] == "completed"


class TestCreateState:
    async def test_creates_state(self, mgmt_mcp, mock_client):
        mock_client.states.set_canned("create", {"id": "s-new"})
        result = await mgmt_mcp.call(
            "create_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="In Review",
            group="started",
            color="#ffa500",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "s-new"
        assert result["data"]["name"] == "In Review"
        assert result["data"]["group"] == "started"
        assert result["data"]["color"] == "#ffa500"

    async def test_rejects_cross_domain_state(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "create_state",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="Foreign State",
            group="started",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_create_state_default_color(self, mgmt_mcp, mock_client):
        mock_client.states.set_canned("create", {"id": "s-new2"})
        result = await mgmt_mcp.call(
            "create_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="Blocked",
            group="started",
        )
        assert result["ok"] is True
        assert result["data"]["color"] == "#6366f1"


class TestUpdateState:
    async def test_rejects_cross_domain_update(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "update_state",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            state_id="s-1",
            name="Renamed",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_updates_state(self, mgmt_mcp, mock_client):
        mock_client.states.set_canned("update", {
            "id": "s-1",
            "name": "Renamed",
            "group": "started",
            "color": "#ff0000",
        })
        result = await mgmt_mcp.call(
            "update_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            state_id="s-1",
            name="Renamed",
            color="#ff0000",
        )
        assert result["ok"] is True
        assert result["data"]["name"] == "Renamed"

    async def test_rejects_empty_update(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "update_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            state_id="s-1",
        )
        assert result["ok"] is False
        assert "At least one" in result["error"]


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

class TestListLabels:
    async def test_returns_labels(self, mgmt_mcp, mock_client):
        mock_client.configure_labels(list_data=[
            {"id": "lbl-1", "name": "case", "color": "#f00"},
            {"id": "lbl-2", "name": "agent-task", "color": "#00f"},
        ])
        result = await mgmt_mcp.call(
            "list_labels",
            workspace_slug="test-workspace",
            project_id="proj-1",
        )
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["name"] == "case"


class TestCreateLabel:
    async def test_rejects_cross_domain_label(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "create_label",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            name="foreign-label",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_creates_label(self, mgmt_mcp, mock_client):
        mock_client.configure_labels(create_data={"id": "lbl-new"})
        result = await mgmt_mcp.call(
            "create_label",
            workspace_slug="test-workspace",
            project_id="proj-1",
            name="urgent-review",
            color="#ff0000",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "lbl-new"
        assert result["data"]["name"] == "urgent-review"
        assert result["data"]["color"] == "#ff0000"


class TestUpdateLabel:
    async def test_rejects_cross_domain_update(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "update_label",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            label_id="lbl-1",
            name="Renamed",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_updates_label(self, mgmt_mcp, mock_client):
        mock_client.labels.set_canned("update", {
            "id": "lbl-1",
            "name": "renamed-label",
            "color": "#00ff00",
        })
        result = await mgmt_mcp.call(
            "update_label",
            workspace_slug="test-workspace",
            project_id="proj-1",
            label_id="lbl-1",
            name="renamed-label",
        )
        assert result["ok"] is True
        assert result["data"]["name"] == "renamed-label"

    async def test_rejects_empty_update(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "update_label",
            workspace_slug="test-workspace",
            project_id="proj-1",
            label_id="lbl-1",
        )
        assert result["ok"] is False
        assert "At least one" in result["error"]


class TestDeleteLabel:
    async def test_rejects_cross_domain_delete(self, mgmt_mcp):
        result = await mgmt_mcp.call(
            "delete_label",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            label_id="lbl-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_deletes_label(self, mgmt_mcp, mock_client):
        result = await mgmt_mcp.call(
            "delete_label",
            workspace_slug="test-workspace",
            project_id="proj-1",
            label_id="lbl-1",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "lbl-1"
        assert result["data"]["status"] == "deleted"
        # Verify SDK call
        calls = mock_client.labels._calls
        delete_calls = [c for c in calls if c[0] == "delete"]
        assert len(delete_calls) == 1
        assert delete_calls[0][1]["label_id"] == "lbl-1"
