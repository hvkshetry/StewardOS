"""DI-based tests for plane-mcp execution tools."""

from unittest.mock import AsyncMock, patch

import pytest

from test_support.mcp import FakeMCP


@pytest.fixture
def execution_mcp(fake_mcp, get_client, mock_client):
    from tools.execution import register_execution_tools
    register_execution_tools(fake_mcp, get_client)
    return fake_mcp


class TestUpdateTaskState:
    async def test_transitions_state(self, execution_mcp, mock_client):
        mock_client.configure_work_items(
            update_data={"id": "wi-1", "state": "state-done"},
        )
        result = await execution_mcp.call(
            "update_task_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            state_id="state-done",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "wi-1"
        assert result["data"]["state"] == "state-done"

    async def test_records_update_call(self, execution_mcp, mock_client):
        mock_client.configure_work_items(
            update_data={"id": "wi-2", "state": "state-ip"},
        )
        await execution_mcp.call(
            "update_task_state",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-2",
            state_id="state-ip",
        )
        calls = mock_client.work_items._calls
        assert len(calls) == 1
        assert calls[0][0] == "update"
        assert calls[0][1]["data"].state == "state-ip"


class TestAddTaskComment:
    async def test_adds_comment_via_sdk(self, execution_mcp, mock_client):
        mock_client.work_items.comments.set_canned(
            "create", {"id": "comment-1"},
        )
        result = await execution_mcp.call(
            "add_task_comment",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            comment_html="<p>Progress update</p>",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "comment-1"
        assert result["data"]["comment_html"] == "<p>Progress update</p>"

    async def test_comment_passes_correct_data(self, execution_mcp, mock_client):
        mock_client.work_items.comments.set_canned("create", {"id": "c-2"})
        await execution_mcp.call(
            "add_task_comment",
            workspace_slug="ws",
            project_id="p1",
            work_item_id="w1",
            comment_html="<p>Test</p>",
        )
        calls = mock_client.work_items.comments._calls
        assert len(calls) == 1
        assert calls[0][0] == "create"
        assert calls[0][1]["data"].comment_html == "<p>Test</p>"


class TestCompleteTask:
    async def test_completes_task_with_done_state(self, execution_mcp, mock_client):
        mock_client.configure_states(list_data=[
            {"id": "state-1", "name": "Backlog", "group": "backlog"},
            {"id": "state-2", "name": "In Progress", "group": "started"},
            {"id": "state-3", "name": "Done", "group": "completed"},
        ])
        mock_client.configure_work_items(
            update_data={"id": "wi-1", "state": "state-3"},
        )
        result = await execution_mcp.call(
            "complete_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is True
        assert result["data"]["state"] == "state-3"
        assert result["data"]["status"] == "completed"

    async def test_returns_error_when_no_done_state(self, execution_mcp, mock_client):
        mock_client.configure_states(list_data=[
            {"id": "state-1", "name": "Backlog", "group": "backlog"},
            {"id": "state-2", "name": "In Progress", "group": "started"},
        ])
        result = await execution_mcp.call(
            "complete_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "no_done_state"

    async def test_finds_done_state_by_group(self, execution_mcp, mock_client):
        mock_client.configure_states(list_data=[
            {"id": "state-1", "name": "Open", "group": "backlog"},
            {"id": "state-2", "name": "Closed", "group": "completed"},
        ])
        mock_client.configure_work_items(
            update_data={"id": "wi-1", "state": "state-2"},
        )
        result = await execution_mcp.call(
            "complete_task",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
        )
        assert result["ok"] is True
        assert result["data"]["state"] == "state-2"


class TestAttachExternalLink:
    @patch("tools.execution.api_post", new_callable=AsyncMock)
    async def test_attaches_link_via_http(self, mock_api_post, execution_mcp):
        mock_api_post.return_value = {"id": "link-1"}
        result = await execution_mcp.call(
            "attach_external_link",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            url="https://docs.example.com/report",
            title="Monthly Report",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "link-1"
        assert result["data"]["url"] == "https://docs.example.com/report"
        assert result["data"]["title"] == "Monthly Report"

        # Verify HTTP call
        mock_api_post.assert_called_once()
        call_path, call_data = mock_api_post.call_args[0]
        assert "/work-items/wi-1/links/" in call_path
        assert call_data["url"] == "https://docs.example.com/report"
        assert call_data["title"] == "Monthly Report"

    @patch("tools.execution.api_post", new_callable=AsyncMock)
    async def test_link_without_title(self, mock_api_post, execution_mcp):
        mock_api_post.return_value = {"id": "link-3"}
        result = await execution_mcp.call(
            "attach_external_link",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            url="https://example.com/raw",
        )
        assert result["ok"] is True
        assert result["data"]["title"] == ""

        call_data = mock_api_post.call_args[0][1]
        assert "title" not in call_data


class TestAttachPaperlessDocument:
    @patch("tools.execution.api_post", new_callable=AsyncMock)
    async def test_attaches_document(self, mock_api_post, execution_mcp):
        mock_api_post.return_value = {"id": "link-doc-1"}
        result = await execution_mcp.call(
            "attach_paperless_document",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            document_id="42",
            title="Tax Return 2025",
            paperless_url="https://docs.example.com",
            tags="tax,annual",
            document_date="2025-04-15",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "link-doc-1"
        assert result["data"]["document_id"] == "42"
        assert "docs.example.com/documents/42/details" in result["data"]["url"]
        assert "[Paperless #42]" in result["data"]["title"]
        assert "Tax Return 2025" in result["data"]["title"]
        assert "tags:tax,annual" in result["data"]["title"]
        assert "date:2025-04-15" in result["data"]["title"]

        # Verify HTTP call includes title
        call_data = mock_api_post.call_args[0][1]
        assert "title" in call_data
        assert "[Paperless #42]" in call_data["title"]

    @patch("tools.execution.api_post", new_callable=AsyncMock)
    async def test_document_without_metadata(self, mock_api_post, execution_mcp):
        mock_api_post.return_value = {"id": "link-doc-2"}
        result = await execution_mcp.call(
            "attach_paperless_document",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            document_id="99",
            title="Simple Doc",
        )
        assert result["ok"] is True
        assert "/documents/99/details" in result["data"]["url"]
        assert "tags:" not in result["data"]["title"]
        assert "date:" not in result["data"]["title"]


class TestAttachWorkItemFile:
    async def test_attaches_file(self, execution_mcp, mock_client):
        mock_client.work_items.attachments.set_canned(
            "create", {"id": "att-1"},
        )
        result = await execution_mcp.call(
            "attach_work_item_file",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            filename="report.pdf",
            file_size=102400,
            mime_type="application/pdf",
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "att-1"
        assert result["data"]["filename"] == "report.pdf"
        assert result["data"]["file_size"] == 102400
        assert result["data"]["mime_type"] == "application/pdf"

        # Verify SDK model was used
        calls = mock_client.work_items.attachments._calls
        assert len(calls) == 1
        assert calls[0][0] == "create"
        create_data = calls[0][1]["data"]
        assert create_data.name == "report.pdf"
        assert create_data.size == 102400
        assert create_data.type == "application/pdf"

    async def test_attaches_file_minimal(self, execution_mcp, mock_client):
        mock_client.work_items.attachments.set_canned(
            "create", {"id": "att-2"},
        )
        result = await execution_mcp.call(
            "attach_work_item_file",
            workspace_slug="test-workspace",
            project_id="proj-1",
            work_item_id="wi-1",
            filename="data.csv",
            file_size=512,
        )
        assert result["ok"] is True
        assert result["data"]["id"] == "att-2"
        assert result["data"]["mime_type"] == ""

        # Verify optional fields not sent
        create_data = mock_client.work_items.attachments._calls[0][1]["data"]
        assert create_data.type is None
        assert create_data.external_id is None
