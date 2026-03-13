from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException

import src.main as main
from src.models import AgentResponse, IncomingEmail


class _FakeRequest:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


def test_webhook_gmail_accepts_valid_payload_and_schedules_background_task():
    background_tasks = BackgroundTasks()
    payload = {"message": {"data": "encoded-pubsub-data"}}

    response = asyncio.run(
        main.webhook_gmail(_FakeRequest(payload), background_tasks)
    )

    assert response == {"status": "accepted"}
    assert len(background_tasks.tasks) == 1
    assert background_tasks.tasks[0].func is main.process_gmail_notification
    assert background_tasks.tasks[0].args == (payload,)


def test_webhook_gmail_rejects_missing_message_data():
    background_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            main.webhook_gmail(_FakeRequest({"message": {}}), background_tasks)
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Missing message data"
    assert background_tasks.tasks == []


def test_process_gmail_notification_routes_allowlisted_email(monkeypatch):
    email = IncomingEmail(
        sender="Parent <parent@example.com>",
        subject="Question",
        body="Can you summarize tomorrow?",
        message_id="msg-1",
        thread_id="thread-1",
    )
    process_family_email = AsyncMock()

    async def fake_process_gmail_webhook(payload: dict, family_emails: list[str]):
        assert payload == {"message": {"data": "pubsub"}}
        assert family_emails == ["parent@example.com"]
        return email

    monkeypatch.setattr(main.settings, "family_emails", ["parent@example.com"])
    monkeypatch.setattr(
        "src.webhook.gmail_handler.process_gmail_webhook",
        fake_process_gmail_webhook,
    )
    monkeypatch.setattr(main, "process_family_email", process_family_email)

    asyncio.run(main.process_gmail_notification({"message": {"data": "pubsub"}}))

    process_family_email.assert_awaited_once_with(email)


def test_process_gmail_notification_ignores_empty_batch(monkeypatch):
    process_family_email = AsyncMock()

    async def fake_process_gmail_webhook(payload: dict, family_emails: list[str]):
        return None

    monkeypatch.setattr(
        "src.webhook.gmail_handler.process_gmail_webhook",
        fake_process_gmail_webhook,
    )
    monkeypatch.setattr(main, "process_family_email", process_family_email)

    asyncio.run(main.process_gmail_notification({"message": {"data": "pubsub"}}))

    process_family_email.assert_not_awaited()


def test_process_family_email_reuses_thread_session_and_persists_latest_session(
    monkeypatch,
):
    email = IncomingEmail(
        sender="Parent <parent@example.com>",
        subject="Need a recap",
        body="Please help with tonight's schedule.",
        message_id="msg-2",
        thread_id="thread-abc",
    )
    captured_call: dict[str, object] = {}
    store_session = AsyncMock()

    async def fake_get_session(thread_id: str):
        assert thread_id == "thread-abc"
        return "existing-session"

    async def fake_call_codex(*, agent_config_dir, prompt, context, session_id):
        captured_call["agent_config_dir"] = agent_config_dir
        captured_call["prompt"] = prompt
        captured_call["context"] = context
        captured_call["session_id"] = session_id
        return AgentResponse(
            success=True,
            response_text="Handled",
            metadata={"session_id": "new-session"},
        )

    monkeypatch.setattr(
        "src.session_store.SessionStore.get_session",
        fake_get_session,
    )
    monkeypatch.setattr(
        "src.session_store.SessionStore.store_session",
        store_session,
    )
    monkeypatch.setattr("src.codex_caller.call_codex", fake_call_codex)
    monkeypatch.setattr(
        main.settings,
        "agent_config_dir_family",
        "/tmp/family-persona",
    )

    asyncio.run(main.process_family_email(email))

    assert captured_call["agent_config_dir"] == "/tmp/family-persona"
    assert captured_call["session_id"] == "existing-session"
    assert "BEGIN EMAIL DATA" in captured_call["prompt"]
    assert "From: Parent <parent@example.com>" in captured_call["context"]
    store_session.assert_awaited_once_with(
        thread_id="thread-abc",
        conversation_id="new-session",
    )


def test_process_family_email_does_not_persist_session_on_failed_agent(monkeypatch):
    email = IncomingEmail(
        sender="Parent <parent@example.com>",
        subject="Need help",
        body="Can you draft a reply?",
        message_id="msg-3",
        thread_id="thread-failed",
    )
    store_session = AsyncMock()

    async def fake_get_session(thread_id: str):
        return "existing-session"

    async def fake_call_codex(*, agent_config_dir, prompt, context, session_id):
        return AgentResponse(
            success=False,
            response_text="",
            error="tool failure",
            metadata={"session_id": "new-session"},
        )

    monkeypatch.setattr(
        "src.session_store.SessionStore.get_session",
        fake_get_session,
    )
    monkeypatch.setattr(
        "src.session_store.SessionStore.store_session",
        store_session,
    )
    monkeypatch.setattr("src.codex_caller.call_codex", fake_call_codex)

    asyncio.run(main.process_family_email(email))

    store_session.assert_not_awaited()
