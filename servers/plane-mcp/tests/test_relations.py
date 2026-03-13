"""DI-based tests for plane-mcp relation tools."""

from unittest.mock import AsyncMock, patch

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def rel_mcp(fake_mcp, get_client):
    from tools.relations import register_relation_tools
    register_relation_tools(fake_mcp, get_client)
    return fake_mcp


class TestListWorkItemRelations:
    async def test_returns_relations(self, rel_mcp):
        canned = [
            {
                "id": "rel-1",
                "relation_type": "blocks",
                "related_issue": "wi-2",
                "issue": "wi-1",
                "created_at": "2026-03-10T10:00:00Z",
            },
            {
                "id": "rel-2",
                "relation_type": "relates_to",
                "related_issue": "wi-3",
                "issue": "wi-1",
                "created_at": "2026-03-10T11:00:00Z",
            },
        ]
        with patch("tools.relations.api_get", new_callable=AsyncMock, return_value=canned):
            result = await rel_mcp.call(
                "list_work_item_relations",
                workspace_slug="test-workspace",
                project_id="proj-1",
                work_item_id="wi-1",
            )
        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["relation_type"] == "blocks"
        assert result["data"][1]["related_issue"] == "wi-3"

    async def test_empty_relations(self, rel_mcp):
        with patch("tools.relations.api_get", new_callable=AsyncMock, return_value=[]):
            result = await rel_mcp.call(
                "list_work_item_relations",
                workspace_slug="test-workspace",
                project_id="proj-1",
                work_item_id="wi-1",
            )
        assert result["ok"] is True
        assert result["data"] == []

    async def test_handles_dict_response_with_results_key(self, rel_mcp):
        canned = {"results": [{"id": "rel-1", "relation_type": "blocks", "related_issue": "wi-2", "issue": "wi-1", "created_at": "2026-03-10T10:00:00Z"}]}
        with patch("tools.relations.api_get", new_callable=AsyncMock, return_value=canned):
            result = await rel_mcp.call(
                "list_work_item_relations",
                workspace_slug="test-workspace",
                project_id="proj-1",
                work_item_id="wi-1",
            )
        assert result["ok"] is True
        assert len(result["data"]) == 1


class TestCreateWorkItemRelation:
    async def test_creates_relation(self, rel_mcp):
        with patch("tools.relations.api_post", new_callable=AsyncMock, return_value={"id": "rel-new"}) as mock_post:
            result = await rel_mcp.call(
                "create_work_item_relation",
                workspace_slug="test-workspace",
                project_id="proj-1",
                work_item_id="wi-1",
                related_work_item_id="wi-2",
                relation_type="blocks",
            )
        assert result["ok"] is True
        assert result["data"]["relation_type"] == "blocks"
        assert result["data"]["related_work_item_id"] == "wi-2"

        # Verify the POST payload
        call_args = mock_post.call_args
        payload = call_args[0][1]
        assert payload["related_list"][0]["issue"] == "wi-2"
        assert payload["related_list"][0]["relation_type"] == "blocks"

    async def test_rejects_cross_domain(self, rel_mcp):
        result = await rel_mcp.call(
            "create_work_item_relation",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            related_work_item_id="wi-2",
            relation_type="blocks",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]

    async def test_rejects_invalid_relation_type(self, rel_mcp):
        result = await rel_mcp.call(
            "create_work_item_relation",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            related_work_item_id="wi-2",
            relation_type="invalid_type",
        )
        assert result["ok"] is False
        assert "Invalid relation_type" in result["error"]

    async def test_all_valid_relation_types(self, rel_mcp):
        for rtype in ("relates_to", "is_blocked_by", "blocks", "is_duplicate_of"):
            with patch("tools.relations.api_post", new_callable=AsyncMock, return_value={"id": "rel-new"}):
                result = await rel_mcp.call(
                    "create_work_item_relation",
                    workspace_slug="test-workspace",
                    project_id="proj-1",
                    work_item_id="wi-1",
                    related_work_item_id="wi-2",
                    relation_type=rtype,
                )
            assert result["ok"] is True, f"Failed for relation_type={rtype}"


class TestDeleteWorkItemRelation:
    async def test_deletes_relation(self, rel_mcp):
        with patch("tools.relations.api_delete", new_callable=AsyncMock) as mock_del:
            result = await rel_mcp.call(
                "delete_work_item_relation",
                workspace_slug="test-workspace",
                project_id="proj-1",
                work_item_id="wi-1",
                relation_id="rel-1",
            )
        assert result["ok"] is True
        assert result["data"]["deleted"] is True
        assert result["data"]["relation_id"] == "rel-1"

        # Verify correct path
        call_path = mock_del.call_args[0][0]
        assert "rel-1" in call_path
        assert "issue-relation" in call_path

    async def test_rejects_cross_domain(self, rel_mcp):
        result = await rel_mcp.call(
            "delete_work_item_relation",
            workspace_slug="foreign-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            relation_id="rel-1",
        )
        assert result["ok"] is False
        assert "foreign-workspace" in result["error"]
        assert "test-workspace" in result["error"]
