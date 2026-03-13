"""Tests for delegation flow (simplified: Plane = source of truth, no local edges)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.config import settings
from src.models import IncomingEmail
from src.session_store import SessionStore


def _reset_session_store(database_path: Path) -> None:
    settings.database_url = f"sqlite+aiosqlite:///{database_path}"
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
    _reset_session_store(tmp_path / "specialist.db")

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
         patch("src.main._complete_plane_work_item", new_callable=AsyncMock) as mock_complete:
        mock_settings.alias_persona_map = {"ra": "research-analyst"}
        mock_settings.resolve_persona_dir.return_value = "/fake/dir"
        mock_settings.plane_base_url = "http://plane"
        mock_settings.plane_api_token = "tok"

        asyncio.run(_handle_plane_work_item_created(data, workspace_slug="investment-office"))

        mock_complete.assert_called_once()


def test_unknown_alias_ignored(tmp_path):
    """Work items with unknown target_alias labels are silently skipped."""
    _reset_session_store(tmp_path / "unknown.db")

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
    _reset_session_store(tmp_path / "nolabel.db")

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
    _reset_session_store(tmp_path / "failure.db")

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
         patch("src.main._complete_plane_work_item", new_callable=AsyncMock) as mock_complete:
        mock_settings.alias_persona_map = {"ra": "research-analyst"}
        mock_settings.resolve_persona_dir.return_value = "/fake/dir"
        mock_settings.plane_base_url = "http://plane"
        mock_settings.plane_api_token = "tok"

        asyncio.run(_handle_plane_work_item_created(data, workspace_slug="investment-office"))

        mock_complete.assert_not_called()


# ─── Email Delegation Branch Tests ──────────────────────────────────────


def test_email_delegation_records_pm_session(tmp_path):
    """When persona returns a delegate ack, PM session metadata is recorded."""
    _reset_session_store(tmp_path / "email-delegate.db")

    # Verify PM session was created
    pm = asyncio.run(SessionStore.get_pm_session_by_case("case-123"))
    assert pm is None  # Nothing yet

    # Simulate what the email handler does on delegate ack
    asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-1",
        case_id="case-123",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))

    pm = asyncio.run(SessionStore.get_pm_session_by_case("case-123"))
    assert pm is not None
    assert pm["lead_alias"] == "cos"
    assert pm["workspace_slug"] == "chief-of-staff"


def test_closed_pm_session_reactivated_on_second_delegation(tmp_path):
    """A closed PM session is reactivated with new case data on re-delegation."""
    _reset_session_store(tmp_path / "reactivate.db")

    # Create and close an initial PM session
    result1 = asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-1",
        case_id="case-old",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))
    assert result1["duplicate"] is False
    asyncio.run(SessionStore.close_pm_session("case-old"))

    pm = asyncio.run(SessionStore.get_pm_session_by_case("case-old"))
    assert pm["status"] == "closed"

    # Second delegation on same session_key reactivates with new case
    result2 = asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-1",
        case_id="case-new",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
    ))
    assert result2["duplicate"] is False
    assert result2["case_id"] == "case-new"

    pm = asyncio.run(SessionStore.get_pm_session_by_case("case-new"))
    assert pm is not None
    assert pm["status"] == "active"
    assert pm["project_id"] == "proj-2"


def test_active_pm_session_returns_duplicate(tmp_path):
    """An active PM session returns duplicate=True on same session_key."""
    _reset_session_store(tmp_path / "dup.db")

    asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-1",
        case_id="case-1",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))

    result = asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-1",
        case_id="case-2",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
    ))
    assert result["duplicate"] is True
    assert result["case_id"] == "case-1"  # Original case preserved


def test_get_pm_session_by_thread_returns_most_recent(tmp_path):
    """get_pm_session_by_thread returns the most recently linked case."""
    _reset_session_store(tmp_path / "thread-order.db")

    # Create two PM sessions with different cases
    asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-old",
        case_id="case-old",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        lead_alias="cos",
    ))
    asyncio.run(SessionStore.link_thread_to_case(
        thread_id="thread-1",
        case_id="case-old",
        workspace_slug="chief-of-staff",
    ))

    # Second link on same thread (different case)
    asyncio.run(SessionStore.create_pm_session(
        session_key="cos:thread-new",
        case_id="case-new",
        workspace_slug="chief-of-staff",
        project_id="proj-2",
        lead_alias="cos",
    ))
    asyncio.run(SessionStore.link_thread_to_case(
        thread_id="thread-1",
        case_id="case-new",
        workspace_slug="chief-of-staff",
    ))

    pm = asyncio.run(SessionStore.get_pm_session_by_thread("thread-1"))
    assert pm is not None
    assert pm["case_id"] == "case-new"
