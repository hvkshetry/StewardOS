"""Tests for canonical Plane coordination tool."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def coordination_mcp(fake_mcp, get_client):
    from tools.coordination import register_coordination_tools

    register_coordination_tools(fake_mcp, get_client)
    return fake_mcp


class TestCoordinationQueue:
    async def test_queue_filters_with_coordination_params(self, coordination_mcp):
        with patch("tools.coordination.api_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "results": [
                    {
                        "id": "wi-1",
                        "name": "Awaiting estate review",
                        "coordination": {"route_to": "estate", "coordination_status": "delegated"},
                    }
                ]
            }

            result = await coordination_mcp.call(
                "coordination",
                operation="queue",
                workspace_slug="test-workspace",
                project_id="proj-1",
                route_to="estate",
                coordination_status="delegated",
            )

        assert result["ok"] is True
        assert result["data"][0]["id"] == "wi-1"
        assert mock_get.call_args.kwargs["params"]["route_to"] == "estate"
        assert mock_get.call_args.kwargs["params"]["coordination_status"] == "delegated"
        assert mock_get.call_args.kwargs["params"]["expand"] == "coordination"


class TestCoordinationDelegate:
    async def test_delegate_creates_case_and_child_tasks(self, coordination_mcp, mock_client):
        mock_client.configure_labels(
            list_data=[
                {"id": "lbl-case", "name": "case", "color": "#000"},
                {"id": "lbl-agent", "name": "agent-task", "color": "#000"},
                {"id": "lbl-human", "name": "human-task", "color": "#000"},
            ]
        )
        mock_client.projects.set_canned(
            "get_members",
            [
                {
                    "id": "user-estate",
                    "display_name": "Estate Counsel",
                    "email": "steward.agent+estate@example.com",
                    "role": 20,
                },
                {
                    "id": "user-Principal",
                    "display_name": "Principal Family",
                    "email": "principal@example.com",
                    "role": 20,
                },
            ],
        )
        mock_client.work_items.create = MagicMock(
            side_effect=[
                {"id": "case-1", "name": "Root case"},
                {"id": "agent-1", "name": "Estate follow-up", "parent": "case-1"},
                {"id": "human-1", "name": "Manual review", "parent": "case-1"},
            ]
        )

        with (
            patch("tools.coordination.api_patch", new_callable=AsyncMock) as mock_patch,
            patch("tools.coordination.api_post", new_callable=AsyncMock) as mock_post,
        ):
            mock_patch.return_value = {"coordination_status": "triaged", "route_to": "cos"}
            mock_post.side_effect = [
                {"coordination_status": "delegated", "route_to": "estate"},
                {"coordination_status": "delegated", "route_to": "Principal"},
            ]
            result = await coordination_mcp.call(
                "coordination",
                operation="delegate",
                workspace_slug="test-workspace",
                project_id="proj-1",
                title="Root case",
                description_html="<p>Root work</p>",
                route_to="cos",
                agent_tasks=[
                    {
                        "title": "Estate follow-up",
                        "description_html": "<p>Investigate trust issue</p>",
                        "target_alias": "estate",
                    }
                ],
                human_tasks=[
                    {
                        "title": "Manual review",
                        "description_html": "<p>Review and approve</p>",
                        "assignee_query": "Principal",
                    }
                ],
            )

        assert result["ok"] is True
        assert result["data"]["case"]["id"] == "case-1"
        assert len(result["data"]["agent_tasks"]) == 1
        assert len(result["data"]["human_tasks"]) == 1
        assert result["data"]["agent_tasks"][0]["route_to"] == "estate"
        assert result["data"]["human_tasks"][0]["route_to"] == "Principal"
        assert result["data"]["agent_tasks"][0]["resolved_assignee"]["id"] == "user-estate"
        assert result["data"]["human_tasks"][0]["resolved_assignee"]["id"] == "user-Principal"
        assert mock_patch.call_args.args[0] == "/workspaces/test-workspace/projects/proj-1/work-items/case-1/coordination/"
        assert mock_post.call_count == 2
        assert mock_post.call_args_list[0].args[0].endswith("/work-items/agent-1/coordination/handoff/")
        assert mock_post.call_args_list[1].args[0].endswith("/work-items/human-1/coordination/handoff/")
