from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

import src.main as main
from src.codex_caller import parse_codex_jsonl
from src.config import settings
from src.main import _ACTION_ACK_MARKER, _build_pubsub_payload, _extract_marked_json, app
from src.models import AgentResponse
from src.session_store import SessionStore


def _reset_session_store(database_path: Path) -> None:
    settings.database_url = f"sqlite+aiosqlite:///{database_path}"
    asyncio.run(SessionStore.reset_for_tests())
    asyncio.run(SessionStore.initialize())


def test_extract_marked_json_requires_explicit_marker():
    payload = (
        f"{_ACTION_ACK_MARKER}"
        '{"action":"reply","status":"ok","sent_message_id":"abc","thread_id":"t1","from_email":"agent@example.com","to":["user@example.com"]}'
    )

    parsed = _extract_marked_json(payload, _ACTION_ACK_MARKER)

    assert parsed is not None
    assert parsed["action"] == "reply"
    assert _extract_marked_json('{"status":"sent"}', _ACTION_ACK_MARKER) is None


def test_parse_codex_jsonl_keeps_mcp_tool_call_completions():
    output = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "mcp_tool_call_end",
                    "invocation": {
                        "server": "google-workspace-agent-rw",
                        "tool": "reply_gmail_message",
                        "arguments": {"message_id": "gmail-message-1"},
                    },
                    "result": {"message_id": "sent-123", "thread_id": "thread-123"},
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "ACTION_ACK_JSON:{\"action\":\"reply\",\"status\":\"ok\"}"},
                }
            ),
        ]
    )

    parsed = parse_codex_jsonl(output)

    assert parsed["session_id"] == "thread-123"
    assert parsed["mcp_tool_calls"] == [
        {
            "server": "google-workspace-agent-rw",
            "tool": "reply_gmail_message",
            "arguments": {"message_id": "gmail-message-1"},
            "result": {"message_id": "sent-123", "thread_id": "thread-123"},
        }
    ]
    assert "ACTION_ACK_JSON" in parsed["text"]


def test_session_store_queue_lifecycle(tmp_path):
    database_path = tmp_path / "mail_worker.sqlite"
    _reset_session_store(database_path)

    enqueue_result = asyncio.run(
        SessionStore.enqueue_gmail_notification(
            event_key="evt-1",
            payload={"message": {"data": "abc"}},
            email="agent@example.com",
            history_id=123,
        )
    )

    assert enqueue_result["duplicate"] is False

    duplicate_result = asyncio.run(
        SessionStore.enqueue_gmail_notification(
            event_key="evt-1",
            payload={"message": {"data": "abc"}},
            email="agent@example.com",
            history_id=123,
        )
    )
    assert duplicate_result["duplicate"] is True

    claimed = asyncio.run(SessionStore.claim_next_notification(claim_timeout_seconds=600))
    assert claimed is not None
    assert claimed["event_key"] == "evt-1"
    assert claimed["status"] == "processing"

    asyncio.run(
        SessionStore.mark_notification_failed(
            claimed["id"],
            error="temporary_failure",
            retry_delay_seconds=1,
        )
    )
    failed = asyncio.run(SessionStore.get_notification_status(claimed["id"]))
    assert failed["status"] == "failed"
    assert failed["last_error"] == "temporary_failure"

    asyncio.run(SessionStore.mark_notification_completed(claimed["id"]))
    completed = asyncio.run(SessionStore.get_notification_status(claimed["id"]))
    assert completed["status"] == "completed"


def test_session_store_claims_multiple_pending_notifications_in_order(tmp_path):
    database_path = tmp_path / "mail_worker.sqlite"
    _reset_session_store(database_path)

    first = asyncio.run(
        SessionStore.enqueue_gmail_notification(
            event_key="evt-1",
            payload={"message": {"data": "abc"}},
            email="agent@example.com",
            history_id=123,
        )
    )
    second = asyncio.run(
        SessionStore.enqueue_gmail_notification(
            event_key="evt-2",
            payload={"message": {"data": "def"}},
            email="agent@example.com",
            history_id=124,
        )
    )

    claimed_first = asyncio.run(SessionStore.claim_next_notification(claim_timeout_seconds=600))
    claimed_second = asyncio.run(SessionStore.claim_next_notification(claim_timeout_seconds=600))

    assert claimed_first is not None
    assert claimed_second is not None
    assert claimed_first["id"] == first["id"]
    assert claimed_second["id"] == second["id"]
    assert claimed_first["event_key"] == "evt-1"
    assert claimed_second["event_key"] == "evt-2"


def test_worker_endpoint_enqueues_before_ack(monkeypatch, tmp_path):
    database_path = tmp_path / "mail_worker.sqlite"
    _reset_session_store(database_path)

    monkeypatch.setattr(settings, "worker_shared_secret", "shared-secret")
    monkeypatch.setattr(settings, "watch_renew_enabled", False)
    monkeypatch.setattr(settings, "scheduled_briefs_enabled", False)
    monkeypatch.setattr(settings, "codex_scratch_dir", str(tmp_path / "scratch"))

    import src.main as main

    monkeypatch.setattr(main, "_schedule_queue_drain", lambda: None)

    payload = _build_pubsub_payload(456)
    payload["message"]["messageId"] = "pubsub-1"

    with TestClient(app) as client:
        response = client.post(
            "/internal/family-office/gmail",
            json=payload,
            headers={"X-Family-Office-Shared-Secret": "shared-secret"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "accepted"
    assert body["duplicate"] is False

    queued = asyncio.run(SessionStore.get_notification_status(body["queue_id"]))
    assert queued is not None
    assert queued["status"] == "pending"


def test_scheduled_brief_uses_gmail_tool_completion_when_ack_missing(monkeypatch):
    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        return AgentResponse(
            success=True,
            response_text="Scheduled send completed without ack marker.",
            metadata={
                "session_id": "scheduled-session-next",
                "mcp_tool_calls": [
                    {
                        "server": "google-workspace-agent-rw",
                        "tool": "send_gmail_message",
                        "result": {"message_id": "scheduled-sent-1", "thread_id": "scheduled-thread-1"},
                    }
                ],
            },
        )

    async def return_none(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(settings, "scheduled_briefs_enabled", True)
    monkeypatch.setattr(settings, "briefing_timezone", "America/New_York")
    monkeypatch.setattr(settings, "agent_configs_root", "/tmp")
    monkeypatch.setitem(settings.alias_persona_map, "io", "io-persona")
    monkeypatch.setitem(settings.alias_display_name_map, "io", "Investment Officer")
    monkeypatch.setattr(main.SessionStore, "get_session", return_none)
    monkeypatch.setattr(main.SessionStore, "store_session", noop)

    main._SCHEDULED_JOB_STATUS.clear()

    asyncio.run(
        main._run_scheduled_brief(
            job_id="io_preopen_monday",
            alias="io",
            recipients=["family@example.com"],
            delivery_mode="email",
        )
    )

    status = main._SCHEDULED_JOB_STATUS["io_preopen_monday"]
    assert status["last_status"] == "sent"
    assert status["last_sent_message_id"] == "scheduled-sent-1"
    assert status["last_thread_id"] == "scheduled-thread-1"
