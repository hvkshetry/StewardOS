from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

sys.path.insert(0, os.path.abspath(str(Path(__file__).resolve().parents[2])))

from src.webhook import gmail_handler


def _build_pubsub_payload(history_id: int) -> dict:
    data = base64.urlsafe_b64encode(
        json.dumps(
            {
                "emailAddress": "steward.agent@example.com",
                "historyId": history_id,
            }
        ).encode("utf-8")
    ).decode("ascii")
    return {
        "message": {
            "data": data,
            "messageId": "pubsub-test-1",
        },
        "subscription": "projects/stewardos-gcp-project/subscriptions/family-gmail-push",
    }


def _http_404() -> HttpError:
    return HttpError(
        Response({"status": "404"}),
        b'{"error":{"message":"Requested entity was not found.","status":"NOT_FOUND"}}',
        uri="https://gmail.googleapis.com/gmail/v1/users/me/messages/missing",
    )


def test_process_gmail_webhook_skips_missing_message_and_keeps_newer_mail(monkeypatch):
    async def fake_get_watch_state(email: str):
        assert email == "steward.agent@example.com"
        return {"history_id": 8433}

    monkeypatch.setattr(gmail_handler.SessionStore, "get_watch_state", fake_get_watch_state)
    monkeypatch.setattr(
        gmail_handler,
        "get_history_pages",
        lambda start_history_id: [
            {
                "messagesAdded": [
                    {"message": {"id": "missing-msg"}},
                    {"message": {"id": "live-msg"}},
                ]
            }
        ],
    )

    def fake_get_email_detail(message_id: str) -> dict:
        if message_id == "missing-msg":
            raise _http_404()
        if message_id == "live-msg":
            return {
                "sender": "Family Principal <principal@example.com>",
                "subject": "Ingest and Tag Docs in Paperless",
                "body_text": "Please ingest this into Paperless.",
                "snippet": "Please ingest this into Paperless.",
                "messageIdHeader": "<live-msg@example.com>",
                "references": "",
                "inReplyTo": "",
                "threadId": "thread-live",
                "recipients": ["steward.agent+cos@example.com"],
            }
        raise AssertionError(f"Unexpected message id {message_id}")

    monkeypatch.setattr(gmail_handler, "get_email_detail", fake_get_email_detail)

    result = asyncio.run(
        gmail_handler.process_gmail_webhook(
            _build_pubsub_payload(8666),
            allowed_senders=["principal@example.com"],
        )
    )

    assert result["cursor_advanced"] is False
    assert result["history_id"] == 8666
    assert len(result["emails"]) == 1
    email = result["emails"][0]
    assert email.message_id == "live-msg"
    assert email.target_alias == "cos"
    assert email.sender_email == "principal@example.com"
    assert email.thread_id == "thread-live"
    assert result["warnings"] == []


def _http_403() -> HttpError:
    return HttpError(
        Response({"status": "403"}),
        b'{"error":{"message":"Forbidden","status":"PERMISSION_DENIED"}}',
        uri="https://gmail.googleapis.com/gmail/v1/users/me/messages/forbidden",
    )


def test_process_gmail_webhook_skips_non_batch_detail_failure_and_keeps_newer_mail(monkeypatch):
    async def fake_get_watch_state(email: str):
        assert email == "steward.agent@example.com"
        return {"history_id": 8433}

    monkeypatch.setattr(gmail_handler.SessionStore, "get_watch_state", fake_get_watch_state)
    monkeypatch.setattr(
        gmail_handler,
        "get_history_pages",
        lambda start_history_id: [
            {
                "messagesAdded": [
                    {"message": {"id": "bad-msg"}},
                    {"message": {"id": "live-msg"}},
                ]
            }
        ],
    )

    def fake_get_email_detail(message_id: str) -> dict:
        if message_id == "bad-msg":
            raise RuntimeError("temporary parse failure")
        if message_id == "live-msg":
            return {
                "sender": "Family Principal <principal@example.com>",
                "subject": "Still process this",
                "body_text": "Keep going.",
                "snippet": "Keep going.",
                "messageIdHeader": "<live-msg@example.com>",
                "references": "",
                "inReplyTo": "",
                "threadId": "thread-live",
                "recipients": ["steward.agent+cos@example.com"],
            }
        raise AssertionError(f"Unexpected message id {message_id}")

    monkeypatch.setattr(gmail_handler, "get_email_detail", fake_get_email_detail)

    result = asyncio.run(
        gmail_handler.process_gmail_webhook(
            _build_pubsub_payload(8667),
            allowed_senders=["principal@example.com"],
        )
    )

    assert result["cursor_advanced"] is False
    assert result["warnings"] == ["message_detail_failed:bad-msg"]
    assert [email.message_id for email in result["emails"]] == ["live-msg"]


def test_process_gmail_webhook_aborts_on_batch_scoped_detail_failure(monkeypatch):
    async def fake_get_watch_state(email: str):
        assert email == "steward.agent@example.com"
        return {"history_id": 8433}

    monkeypatch.setattr(gmail_handler.SessionStore, "get_watch_state", fake_get_watch_state)
    monkeypatch.setattr(
        gmail_handler,
        "get_history_pages",
        lambda start_history_id: [{"messagesAdded": [{"message": {"id": "forbidden-msg"}}]}],
    )
    monkeypatch.setattr(gmail_handler, "get_email_detail", lambda message_id: (_ for _ in ()).throw(_http_403()))

    with pytest.raises(HttpError):
        asyncio.run(
            gmail_handler.process_gmail_webhook(
                _build_pubsub_payload(8668),
                allowed_senders=["principal@example.com"],
            )
        )


def test_process_gmail_webhook_skips_generic_message_detail_failure(monkeypatch):
    async def fake_get_watch_state(email: str):
        assert email == "steward.agent@example.com"
        return {"history_id": 8433}

    monkeypatch.setattr(gmail_handler.SessionStore, "get_watch_state", fake_get_watch_state)
    monkeypatch.setattr(
        gmail_handler,
        "get_history_pages",
        lambda start_history_id: [
            {
                "messagesAdded": [
                    {"message": {"id": "broken-msg"}},
                    {"message": {"id": "live-msg"}},
                ]
            }
        ],
    )

    def fake_get_email_detail(message_id: str) -> dict:
        if message_id == "broken-msg":
            raise RuntimeError("transient gmail detail failure")
        if message_id == "live-msg":
            return {
                "sender": "Family Principal <principal@example.com>",
                "subject": "Weekly update",
                "body_text": "The later message should still process.",
                "snippet": "The later message should still process.",
                "messageIdHeader": "<live-msg@example.com>",
                "references": "",
                "inReplyTo": "",
                "threadId": "thread-live",
                "recipients": ["steward.agent+cos@example.com"],
            }
        raise AssertionError(f"Unexpected message id {message_id}")

    monkeypatch.setattr(gmail_handler, "get_email_detail", fake_get_email_detail)

    result = asyncio.run(
        gmail_handler.process_gmail_webhook(
            _build_pubsub_payload(8666),
            allowed_senders=["principal@example.com"],
        )
    )

    assert result["cursor_advanced"] is False
    assert result["history_id"] == 8666
    assert [email.message_id for email in result["emails"]] == ["live-msg"]
    assert result["warnings"] == ["message_detail_failed:broken-msg"]
