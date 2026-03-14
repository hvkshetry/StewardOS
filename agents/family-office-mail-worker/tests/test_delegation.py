"""Tests for delegation flow (unified Case model, Plane = source of truth)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch


async def _passthrough_ordering(key, coro):
    """Test bypass for _execute_with_ordering — just await the coroutine."""
    return await coro

from conftest import get_test_database_url
from src.config import settings
from src.models import IncomingEmail
from src.session_store import SessionStore


def _reset_session_store(tmp_path: Path) -> None:
    settings.database_url = get_test_database_url(tmp_path)
    asyncio.run(SessionStore.reset_for_tests())
    asyncio.run(SessionStore.initialize())


def _make_email(**overrides) -> IncomingEmail:
    defaults = dict(
        sender="Alice",
        sender_email="alice@example.com",
        subject="Test delegation",
        body="Please handle this.",
        message_id="msg-1",
        thread_id="thread-1",
    )
    defaults.update(overrides)
    return IncomingEmail(**defaults)


# ─── Specialist Webhook Handler Tests ───────────────────────────────────


def test_specialist_executes_task_directly(tmp_path):
    """Specialist receives a Plane task and executes it, transitioning to done."""
    _reset_session_store(tmp_path)

    from src.main import _handle_plane_work_item_created

    data = {
        "id": "task-abc",
        "name": "Research task",
        "description_stripped": "Analyze market trends",
        "labels": [{"name": "target_alias:ra"}],
        "project": "proj-1",
    }

    mock_result = AsyncMock()
    mock_result.success = True
    mock_result.response_text = (
        'ACTION_ACK_JSON: {"action": "maintenance", "status": "ok", '
        '"operation": "research", "summary": "Analysis complete"}'
    )
    mock_result.metadata = {"session_id": "codex-1"}
    mock_result.error = None

    with patch("src.main.settings") as mock_settings, \
         patch("src.main.call_codex", new_callable=AsyncMock, return_value=mock_result), \
         patch("src.main._complete_plane_work_item", new_callable=AsyncMock) as mock_complete, \
         patch("src.main._execute_with_ordering", new=_passthrough_ordering):
        mock_settings.alias_persona_map = {"ra": "research-analyst"}
        mock_settings.resolve_persona_dir.return_value = "/fake/dir"
        mock_settings.plane_base_url = "http://plane"
        mock_settings.plane_api_token = "tok"

        asyncio.run(_handle_plane_work_item_created(data, workspace_slug="investment-office"))

        mock_complete.assert_called_once()


def test_unknown_alias_ignored(tmp_path):
    """Work items with unknown target_alias labels are silently skipped."""
    _reset_session_store(tmp_path)

    from src.main import _handle_plane_work_item_created

    data = {
        "id": "task-xyz",
        "name": "Unknown task",
        "description_stripped": "Something",
        "labels": [{"name": "target_alias:nonexistent"}],
        "project": "proj-1",
    }

    with patch("src.main.settings") as mock_settings, \
         patch("src.main.call_codex", new_callable=AsyncMock) as mock_codex:
        mock_settings.alias_persona_map = {"ra": "research-analyst"}

        asyncio.run(_handle_plane_work_item_created(data, workspace_slug="investment-office"))

        mock_codex.assert_not_called()


def test_no_target_alias_label_ignored(tmp_path):
    """Work items without target_alias labels are silently skipped."""
    _reset_session_store(tmp_path)

    from src.main import _handle_plane_work_item_created

    data = {
        "id": "task-nolabel",
        "name": "Regular task",
        "description_stripped": "A task with no alias",
        "labels": [{"name": "priority:high"}],
        "project": "proj-1",
    }

    with patch("src.main.call_codex", new_callable=AsyncMock) as mock_codex:
        asyncio.run(_handle_plane_work_item_created(data, workspace_slug="investment-office"))

        mock_codex.assert_not_called()


def test_specialist_failure_does_not_complete_item(tmp_path):
    """When Codex fails, the work item is NOT transitioned to done."""
    _reset_session_store(tmp_path)

    from src.main import _handle_plane_work_item_created

    data = {
        "id": "task-fail",
        "name": "Failing task",
        "description_stripped": "Will fail",
        "labels": [{"name": "target_alias:ra"}],
        "project": "proj-1",
    }

    mock_result = AsyncMock()
    mock_result.success = False
    mock_result.response_text = ""
    mock_result.metadata = {}
    mock_result.error = "Codex crashed"

    with patch("src.main.settings") as mock_settings, \
         patch("src.main.call_codex", new_callable=AsyncMock, return_value=mock_result), \
         patch("src.main._complete_plane_work_item", new_callable=AsyncMock) as mock_complete, \
         patch("src.main._execute_with_ordering", new=_passthrough_ordering):
        mock_settings.alias_persona_map = {"ra": "research-analyst"}
        mock_settings.resolve_persona_dir.return_value = "/fake/dir"
        mock_settings.plane_base_url = "http://plane"
        mock_settings.plane_api_token = "tok"

        asyncio.run(_handle_plane_work_item_created(data, workspace_slug="investment-office"))

        mock_complete.assert_not_called()


# ─── Unified Case Record Tests ──────────────────────────────────────────


def test_upsert_case_creates_and_returns(tmp_path):
    """upsert_case creates a new case record with structured_input."""
    _reset_session_store(tmp_path)

    result = asyncio.run(SessionStore.upsert_case(
        case_id="case-123",
        session_key="gmail:cos:thread-1",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
        thread_id="thread-1",
        reply_actor="cos",
        structured_input={
            "original_email_body": "Please handle this.",
            "delegation_rationale": "Test case",
        },
    ))
    assert result["duplicate"] is False
    assert result["case_id"] == "case-123"

    case = asyncio.run(SessionStore.get_case("case-123"))
    assert case is not None
    assert case["lead_alias"] == "cos"
    assert case["reply_actor"] == "cos"
    assert case["workspace_slug"] == "chief-of-staff"
    assert case["structured_input"]["original_email_body"] == "Please handle this."
    assert case["thread_id"] == "thread-1"


def test_closed_case_reactivated_on_second_delegation(tmp_path):
    """A closed case is reactivated with new data on re-delegation."""
    _reset_session_store(tmp_path)

    asyncio.run(SessionStore.upsert_case(
        case_id="case-old",
        session_key="gmail:cos:thread-1",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))
    asyncio.run(SessionStore.close_case("case-old"))

    case = asyncio.run(SessionStore.get_case("case-old"))
    assert case["status"] == "closed"

    result = asyncio.run(SessionStore.upsert_case(
        case_id="case-new",
        session_key="gmail:cos:thread-1",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
        structured_input={"delegation_rationale": "Second delegation"},
    ))
    assert result["duplicate"] is False
    assert result["case_id"] == "case-new"

    case = asyncio.run(SessionStore.get_case("case-new"))
    assert case is not None
    assert case["status"] == "active"
    assert case["project_id"] == "proj-2"
    assert case["structured_input"]["delegation_rationale"] == "Second delegation"


def test_active_case_returns_duplicate(tmp_path):
    """An active case returns duplicate=True on same session_key."""
    _reset_session_store(tmp_path)

    asyncio.run(SessionStore.upsert_case(
        case_id="case-1",
        session_key="gmail:cos:thread-1",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))

    result = asyncio.run(SessionStore.upsert_case(
        case_id="case-2",
        session_key="gmail:cos:thread-1",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
    ))
    assert result["duplicate"] is True
    assert result["case_id"] == "case-1"


def test_get_case_by_thread_returns_most_recent(tmp_path):
    """get_case_by_thread returns the most recently created case."""
    _reset_session_store(tmp_path)

    asyncio.run(SessionStore.upsert_case(
        case_id="case-old",
        session_key="gmail:cos:thread-old",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
        thread_id="thread-1",
    ))

    asyncio.run(SessionStore.upsert_case(
        case_id="case-new",
        session_key="gmail:cos:thread-new",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
        thread_id="thread-1",
    ))

    case = asyncio.run(SessionStore.get_case_by_thread("thread-1"))
    assert case is not None
    assert case["case_id"] == "case-new"


def test_update_case_updates_structured_input(tmp_path):
    """update_case modifies specific fields without touching others."""
    _reset_session_store(tmp_path)

    asyncio.run(SessionStore.upsert_case(
        case_id="case-upd",
        session_key="gmail:cos:thread-upd",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
        structured_input={"original_email_body": "Original"},
        last_human_email_body="Progress email HTML",
    ))

    asyncio.run(SessionStore.update_case(
        "case-upd",
        structured_input={"original_email_body": "Original", "delegation_rationale": "Updated rationale"},
    ))

    case = asyncio.run(SessionStore.get_case("case-upd"))
    assert case["structured_input"]["delegation_rationale"] == "Updated rationale"
    assert case["structured_input"]["original_email_body"] == "Original"
    # last_human_email_body should be unchanged
    assert case["last_human_email_body"] == "Progress email HTML"


def test_get_active_case_workspaces(tmp_path):
    """get_active_case_workspaces returns distinct workspace slugs."""
    _reset_session_store(tmp_path)

    asyncio.run(SessionStore.upsert_case(
        case_id="case-1",
        session_key="gmail:cos:thread-1",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))
    asyncio.run(SessionStore.upsert_case(
        case_id="case-2",
        session_key="gmail:estate:thread-2",
        workspace_slug="estate-counsel",
        project_id="proj-2",
        lead_alias="estate",
    ))
    asyncio.run(SessionStore.upsert_case(
        case_id="case-3",
        session_key="gmail:cos:thread-3",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))
    asyncio.run(SessionStore.close_case("case-3"))

    workspaces = asyncio.run(SessionStore.get_active_case_workspaces())
    assert set(workspaces) == {"chief-of-staff", "estate-counsel"}


def test_get_active_case_project_ids(tmp_path):
    """get_active_case_project_ids returns distinct project IDs for a workspace."""
    _reset_session_store(tmp_path)

    asyncio.run(SessionStore.upsert_case(
        case_id="case-a",
        session_key="gmail:cos:thread-a",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))
    asyncio.run(SessionStore.upsert_case(
        case_id="case-b",
        session_key="gmail:cos:thread-b",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
    ))

    pids = asyncio.run(SessionStore.get_active_case_project_ids("chief-of-staff"))
    assert set(pids) == {"proj-1", "proj-2"}

    # No active cases in this workspace
    pids_empty = asyncio.run(SessionStore.get_active_case_project_ids("estate-counsel"))
    assert pids_empty == []
