"""Gmail API wrappers for mailbox history, message details, and watch management."""

import base64
import logging
import re
from email.message import EmailMessage
from typing import Optional

from src.google.auth import get_gmail_service

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _extract_body(payload: dict) -> tuple[str, str]:
    """Extract text/plain and text/html payloads from Gmail message parts."""
    body_text = ""
    body_html = ""

    def walk(part: dict) -> None:
        nonlocal body_text, body_html
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")
        if data:
            try:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            if mime_type == "text/plain" and decoded and not body_text:
                body_text = decoded
            elif mime_type == "text/html" and decoded and not body_html:
                body_html = decoded

        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return body_text, body_html


def get_history(
    start_history_id: str,
    history_types: Optional[list[str]] = None,
    page_token: Optional[str] = None,
) -> dict:
    """Fetch one page of incremental Gmail history from a given history ID."""
    service = get_gmail_service()
    if history_types is None:
        history_types = ["messageAdded"]

    params = {
        "userId": "me",
        "startHistoryId": start_history_id,
        "historyTypes": history_types,
        "labelId": "INBOX",
    }
    if page_token:
        params["pageToken"] = page_token

    return service.users().history().list(**params).execute()


def get_history_pages(
    start_history_id: str,
    history_types: Optional[list[str]] = None,
    max_pages: int = 20,
) -> list[dict]:
    """Fetch and flatten paginated Gmail history records."""
    page_token = None
    pages = 0
    records: list[dict] = []

    while pages < max_pages:
        response = get_history(
            start_history_id=start_history_id,
            history_types=history_types,
            page_token=page_token,
        )
        records.extend(response.get("history", []))
        page_token = response.get("nextPageToken")
        pages += 1
        if not page_token:
            break

    return records


def get_email_detail(message_id: str) -> dict:
    """Fetch full Gmail message detail by message id."""
    service = get_gmail_service()
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers_list = msg.get("payload", {}).get("headers", [])
    headers = {h.get("name", ""): h.get("value", "") for h in headers_list}
    body_text, body_html = _extract_body(msg.get("payload", {}))

    recipients = []
    for name in ("To", "Cc", "Delivered-To", "X-Original-To"):
        recipients.extend(_EMAIL_RE.findall(headers.get(name, "")))

    return {
        "id": msg.get("id", ""),
        "threadId": msg.get("threadId", ""),
        "sender": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "messageIdHeader": headers.get("Message-ID", ""),
        "references": headers.get("References", ""),
        "inReplyTo": headers.get("In-Reply-To", ""),
        "body_text": body_text,
        "body_html": body_html,
        "snippet": msg.get("snippet", ""),
        "recipients": recipients,
    }


def send_thread_reply(
    to: list[str],
    subject: str,
    body_text: str,
    from_email: str,
    from_name: str,
    thread_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> dict:
    """Send a reply via Gmail API, preserving thread linkage when possible."""
    service = get_gmail_service()

    message = EmailMessage()
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>"

    if in_reply_to:
        message["In-Reply-To"] = in_reply_to

    if references:
        message["References"] = references
    elif in_reply_to:
        message["References"] = in_reply_to

    message.set_content(body_text)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    result = service.users().messages().send(userId="me", body=body).execute()
    logger.info(
        "Reply sent: id=%s thread=%s to=%s",
        result.get("id", ""),
        result.get("threadId", ""),
        ",".join(to),
    )
    return result


def setup_gmail_watch(topic_name: str) -> dict:
    """Create/renew Gmail Pub/Sub watch for inbox notifications."""
    service = get_gmail_service()
    body = {"topicName": topic_name, "labelIds": ["INBOX"]}
    return service.users().watch(userId="me", body=body).execute()


def get_profile_history_id() -> int:
    """Return current mailbox history cursor from Gmail profile."""
    service = get_gmail_service()
    profile = service.users().getProfile(userId="me").execute()
    return int(profile.get("historyId", "0"))
