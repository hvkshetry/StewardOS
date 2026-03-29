from __future__ import annotations

import asyncio
import json
import logging

import src.main as main
from src.models import AgentResponse, IncomingEmail


async def _passthrough_ordering(key, coro):
    """Test bypass for _execute_with_ordering — just await the coroutine."""
    return await coro


def _patch_ordering(monkeypatch):
    """Bypass _execute_with_ordering so tests don't need the semaphore/lock machinery."""
    monkeypatch.setattr(main, "_execute_with_ordering", _passthrough_ordering)


def test_inbound_reply_prompt_uses_reply_tool(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        captured["prompt"] = prompt
        captured["context"] = context or ""
        captured["agent_config_dir"] = agent_config_dir
        return AgentResponse(
            success=True,
            response_text=(
                f'{main._ACTION_ACK_MARKER}'
                + json.dumps(
                    {
                        "action": "reply",
                        "status": "ok",
                        "sent_message_id": "sent-123",
                        "thread_id": "thread-123",
                        "from_email": "steward.agent+cos@example.com",
                        "to": ["family@example.com"],
                    }
                )
            ),
            metadata={
                "session_id": "session-123",
                "mcp_tool_calls": [
                    {
                        "server": "google-workspace-agent-rw",
                        "tool": "reply_gmail_message",
                        "result": {"message_id": "sent-123", "thread_id": "thread-123"},
                    }
                ],
            },
        )

    async def return_false(*args, **kwargs):
        return False

    async def return_none(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return None

    _patch_ordering(monkeypatch)
    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(main.SessionStore, "is_message_processed", return_false)
    monkeypatch.setattr(main.SessionStore, "get_session", return_none)
    monkeypatch.setattr(main.SessionStore, "get_case_by_thread", return_none)
    monkeypatch.setattr(main, "_hydrate_case_from_plane_thread", return_none)
    monkeypatch.setattr(main.SessionStore, "record_message_result", noop)
    monkeypatch.setattr(main.SessionStore, "store_session", noop)

    email = IncomingEmail(
        sender="Family Member <family@example.com>",
        sender_email="family@example.com",
        subject="Need a reply",
        body="Can you handle this?",
        message_id="gmail-message-1",
        thread_id="thread-123",
        internet_message_id="<rfc-message@example.com>",
        recipient_addresses=["steward.agent+cos@example.com"],
        target_alias="cos",
    )

    sent = asyncio.run(main._run_persona_and_reply(email))

    assert sent is True
    prompt = captured["prompt"]
    assert "google-workspace-agent-rw.reply_gmail_message" in prompt
    assert "google-workspace-agent-rw.send_gmail_message" not in prompt
    assert "native reply-all" not in prompt
    assert "Use the relevant skills available in this workspace when they help" in prompt
    assert "Prefer the combination that produces the best answer and the clearest explanation" in prompt
    assert "Keep the workflow proportional to the email" in prompt
    assert "ingest, file, tag, or classify attached documents in Paperless" in prompt
    assert "paperless.post_document" in prompt
    assert "local config or environment inspection" in prompt
    assert "`list_mcp_resources` / `list_mcp_resource_templates`" in prompt
    assert "natural, human-like reply in prose-first HTML that reads like a real human-drafted email" in prompt
    assert "Start with a natural salutation" in prompt
    assert "Open the body with the direct answer or key response in the first paragraph" in prompt
    assert "Render the reply body as actual HTML email content" in prompt
    assert "clean clickable source links" in prompt
    assert "End with a natural closing and persona sign-off" in prompt
    assert "Keep attribution inline by default when material" in prompt
    assert "Use a short final source note only when the reply is research-heavy" in prompt
    assert "Do not force KPI cards, dashboards, or a provenance table into routine replies" in prompt
    assert "plane-pm.coordination" in prompt
    assert 'operation="delegate"' in prompt
    assert 'external_source="gmail_thread"' in prompt
    assert "plane-pm.create_case" not in prompt
    assert "plane-pm.create_agent_task" not in prompt
    assert "Executive Summary (2-minute scan)" not in prompt
    assert "Deep Dive and Data Provenance" not in prompt
    assert "`family-email-formatting` in `reply` mode" not in prompt
    assert "`portfolio-review`" not in prompt
    assert "portfolio implications" not in prompt
    assert "broader analysis only when the reply truly depends on it" not in prompt
    assert '- message_id: "gmail-message-1"' in prompt
    assert "- to:" not in prompt
    assert "- thread_id:" not in prompt
    assert "- in_reply_to:" not in prompt
    assert "- references:" not in prompt
    assert "Gmail message id: gmail-message-1" in captured["context"]


def test_inbound_reply_reuses_thread_session(monkeypatch):
    captured: dict[str, str | None] = {}
    stored: dict[str, str] = {}

    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        captured["session_id"] = session_id
        return AgentResponse(
            success=True,
            response_text=(
                f'{main._ACTION_ACK_MARKER}'
                + json.dumps(
                    {
                        "action": "reply",
                        "status": "ok",
                        "sent_message_id": "sent-456",
                        "thread_id": "thread-abc",
                        "from_email": "steward.agent+cos@example.com",
                        "to": ["family@example.com"],
                    }
                )
            ),
            metadata={
                "session_id": "session-next",
                "mcp_tool_calls": [
                    {
                        "server": "google-workspace-agent-rw",
                        "tool": "reply_gmail_message",
                        "result": {"message_id": "sent-456", "thread_id": "thread-abc"},
                    }
                ],
            },
        )

    async def return_false(*args, **kwargs):
        return False

    async def return_existing_session(session_key):
        captured["session_key"] = session_key
        return "session-existing"

    async def record_session(session_key, conversation_id):
        stored["session_key"] = session_key
        stored["conversation_id"] = conversation_id

    async def noop(*args, **kwargs):
        return None

    _patch_ordering(monkeypatch)
    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(main.SessionStore, "is_message_processed", return_false)
    monkeypatch.setattr(main.SessionStore, "get_session", return_existing_session)
    monkeypatch.setattr(main.SessionStore, "get_case_by_thread", noop)
    monkeypatch.setattr(main, "_hydrate_case_from_plane_thread", noop)
    monkeypatch.setattr(main.SessionStore, "record_message_result", noop)
    monkeypatch.setattr(main.SessionStore, "store_session", record_session)

    email = IncomingEmail(
        sender="Family Member <family@example.com>",
        sender_email="family@example.com",
        subject="Follow-up",
        body="Need another reply",
        message_id="gmail-message-2",
        thread_id="thread-abc",
        internet_message_id="<thread-abc@example.com>",
        recipient_addresses=["steward.agent+cos@example.com"],
        target_alias="cos",
    )

    sent = asyncio.run(main._run_persona_and_reply(email))

    assert sent is True
    assert captured["session_key"] == "gmail:cos:thread-abc"
    assert captured["session_id"] == "session-existing"
    assert stored["session_key"] == "gmail:cos:thread-abc"
    assert stored["conversation_id"] == "session-next"


def test_scheduled_prompt_still_uses_send_gmail_message():
    prompt = main._scheduled_prompt(
        job_id="io_preopen_monday",
        recipients=["family@example.com"],
        subject="Weekly note",
        from_email="steward.agent+io@example.com",
        from_name="Investment Officer",
        tz_name="America/New_York",
    )

    assert "google-workspace-agent-rw.send_gmail_message" in prompt
    assert "reply_gmail_message" not in prompt
    assert "`family-email-formatting` in `brief` mode" in prompt
    assert "Use executive summary first, then deep dive + provenance." in prompt
    assert "agent-chosen primary visual only when it materially improves the brief" in prompt
    assert "Signal Graph" not in prompt


def test_inbound_reply_requires_gmail_tool_completion(monkeypatch):
    recorded: list[dict[str, str | None]] = []

    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        return AgentResponse(
            success=True,
            response_text=(
                f'{main._ACTION_ACK_MARKER}'
                + json.dumps(
                    {
                        "action": "reply",
                        "status": "ok",
                        "sent_message_id": "sent-789",
                        "thread_id": "thread-missing-tool",
                        "from_email": "steward.agent+cos@example.com",
                        "to": ["family@example.com"],
                    }
                )
            ),
            metadata={"session_id": "session-123"},
        )

    async def return_false(*args, **kwargs):
        return False

    async def return_none(*args, **kwargs):
        return None

    async def record_message_result(**kwargs):
        recorded.append(kwargs)

    _patch_ordering(monkeypatch)
    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(main.SessionStore, "is_message_processed", return_false)
    monkeypatch.setattr(main.SessionStore, "get_session", return_none)
    monkeypatch.setattr(main.SessionStore, "get_case_by_thread", return_none)
    monkeypatch.setattr(main, "_hydrate_case_from_plane_thread", return_none)
    monkeypatch.setattr(main.SessionStore, "record_message_result", record_message_result)
    monkeypatch.setattr(main.SessionStore, "store_session", return_none)

    email = IncomingEmail(
        sender="Family Member <family@example.com>",
        sender_email="family@example.com",
        subject="Need a reply",
        body="Can you handle this?",
        message_id="gmail-message-tool-missing",
        thread_id="thread-missing-tool",
        recipient_addresses=["steward.agent+cos@example.com"],
        target_alias="cos",
    )

    sent = asyncio.run(main._run_persona_and_reply(email))

    assert sent is False
    assert recorded[-1]["status"] == "failed"
    assert recorded[-1]["error"] == "missing_gmail_send_result"


def test_inbound_reply_uses_tool_result_when_ack_missing(monkeypatch):
    recorded: list[dict[str, str | None]] = []

    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        return AgentResponse(
            success=True,
            response_text="Reply completed without ack marker.",
            metadata={
                "session_id": "session-456",
                "mcp_tool_calls": [
                    {
                        "server": "google-workspace-agent-rw",
                        "tool": "reply_gmail_message",
                        "result": {"message_id": "sent-from-tool", "thread_id": "thread-tool"},
                    }
                ],
            },
        )

    async def return_false(*args, **kwargs):
        return False

    async def return_none(*args, **kwargs):
        return None

    async def record_message_result(**kwargs):
        recorded.append(kwargs)

    _patch_ordering(monkeypatch)
    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(main.SessionStore, "is_message_processed", return_false)
    monkeypatch.setattr(main.SessionStore, "get_session", return_none)
    monkeypatch.setattr(main.SessionStore, "get_case_by_thread", return_none)
    monkeypatch.setattr(main, "_hydrate_case_from_plane_thread", return_none)
    monkeypatch.setattr(main.SessionStore, "record_message_result", record_message_result)
    monkeypatch.setattr(main.SessionStore, "store_session", return_none)

    email = IncomingEmail(
        sender="Family Member <family@example.com>",
        sender_email="family@example.com",
        subject="Need a reply",
        body="Can you handle this?",
        message_id="gmail-message-ack-missing",
        thread_id="thread-tool",
        recipient_addresses=["steward.agent+cos@example.com"],
        target_alias="cos",
    )

    sent = asyncio.run(main._run_persona_and_reply(email))

    assert sent is True
    assert recorded[-1]["status"] == "sent"
    assert recorded[-1]["thread_id"] == "thread-tool"
    assert recorded[-1]["sent_message_id"] == "sent-from-tool"


def test_inbound_reply_prefers_tool_result_when_ack_mismatches(monkeypatch, caplog):
    recorded: list[dict[str, str | None]] = []

    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        return AgentResponse(
            success=True,
            response_text=(
                f'{main._ACTION_ACK_MARKER}'
                + json.dumps(
                    {
                        "action": "reply",
                        "status": "ok",
                        "sent_message_id": "ack-message-id",
                        "thread_id": "ack-thread-id",
                        "from_email": "steward.agent+cos@example.com",
                        "to": ["family@example.com"],
                    }
                )
            ),
            metadata={
                "session_id": "session-789",
                "mcp_tool_calls": [
                    {
                        "server": "google-workspace-agent-rw",
                        "tool": "reply_gmail_message",
                        "result": {"message_id": "tool-message-id", "thread_id": "tool-thread-id"},
                    }
                ],
            },
        )

    async def return_false(*args, **kwargs):
        return False

    async def return_none(*args, **kwargs):
        return None

    async def record_message_result(**kwargs):
        recorded.append(kwargs)

    _patch_ordering(monkeypatch)
    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(main.SessionStore, "is_message_processed", return_false)
    monkeypatch.setattr(main.SessionStore, "get_session", return_none)
    monkeypatch.setattr(main.SessionStore, "get_case_by_thread", return_none)
    monkeypatch.setattr(main, "_hydrate_case_from_plane_thread", return_none)
    monkeypatch.setattr(main.SessionStore, "record_message_result", record_message_result)
    monkeypatch.setattr(main.SessionStore, "store_session", return_none)

    email = IncomingEmail(
        sender="Family Member <family@example.com>",
        sender_email="family@example.com",
        subject="Need a reply",
        body="Can you handle this?",
        message_id="gmail-message-ack-mismatch",
        thread_id="thread-tool",
        recipient_addresses=["steward.agent+cos@example.com"],
        target_alias="cos",
    )

    with caplog.at_level(logging.WARNING):
        sent = asyncio.run(main._run_persona_and_reply(email))

    assert sent is True
    assert recorded[-1]["status"] == "sent"
    assert recorded[-1]["thread_id"] == "tool-thread-id"
    assert recorded[-1]["sent_message_id"] == "tool-message-id"
    assert "send ack mismatched tool result fields" in caplog.text


def test_scheduled_brief_uses_tool_result_when_ack_missing(monkeypatch):
    async def fake_call_codex(*, prompt, agent_config_dir, context=None, session_id=None):
        return AgentResponse(
            success=True,
            response_text="Brief completed without ack marker.",
            metadata={
                "session_id": "session-scheduled",
                "mcp_tool_calls": [
                    {
                        "server": "google-workspace-agent-rw",
                        "tool": "send_gmail_message",
                        "result": {"message_id": "scheduled-from-tool", "thread_id": "scheduled-thread"},
                    }
                ],
            },
        )

    async def return_none(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "call_codex", fake_call_codex)
    monkeypatch.setattr(main.SessionStore, "get_session", return_none)
    monkeypatch.setattr(main.SessionStore, "store_session", return_none)
    main._SCHEDULED_JOB_STATUS.clear()
    main._SCHEDULED_JOB_LOCKS.clear()

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
    assert status["last_thread_id"] == "scheduled-thread"
    assert status["last_sent_message_id"] == "scheduled-from-tool"
