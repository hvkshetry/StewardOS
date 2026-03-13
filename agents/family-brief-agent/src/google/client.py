"""Google API client wrappers for Gmail and Calendar.

Thin wrappers around the Google API client libraries. All methods use the
authenticated service objects from src.google.auth.
"""

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from src.google.auth import get_calendar_service, get_gmail_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gmail
# ---------------------------------------------------------------------------

def send_email(to: list[str], subject: str, body_html: str) -> dict:
    """Send an email via the Gmail API.

    Args:
        to: List of recipient email addresses.
        subject: Email subject line.
        body_html: Email body as HTML.

    Returns:
        Gmail API send response dict (contains id, threadId, labelIds).
    """
    service = get_gmail_service()

    message = MIMEMultipart("alternative")
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.attach(MIMEText(body_html, "html"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    body = {"raw": raw}

    result = service.users().messages().send(userId="me", body=body).execute()
    logger.info(f"Email sent: id={result.get('id')}, to={to}, subject={subject}")
    return result


def get_unread_emails(user_email: str, max_results: int = 20) -> list[dict]:
    """Get recent unread emails from the inbox.

    Args:
        user_email: The Gmail address (used for logging; API uses 'me').
        max_results: Maximum number of messages to return.

    Returns:
        List of message metadata dicts with id, threadId, snippet, sender, subject.
    """
    service = get_gmail_service()

    response = service.users().messages().list(
        userId="me",
        labelIds=["INBOX", "UNREAD"],
        maxResults=max_results,
    ).execute()

    messages = response.get("messages", [])
    results = []

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me",
            id=msg_ref["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"],
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        results.append({
            "id": msg["id"],
            "threadId": msg.get("threadId", ""),
            "snippet": msg.get("snippet", ""),
            "sender": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
        })

    logger.info(f"Fetched {len(results)} unread emails for {user_email}")
    return results


def get_email_detail(user_email: str, message_id: str) -> dict:
    """Get full email content by message ID.

    Args:
        user_email: The Gmail address (used for logging; API uses 'me').
        message_id: The Gmail message ID.

    Returns:
        Dict with id, threadId, sender, subject, body_text, body_html, snippet.
    """
    service = get_gmail_service()

    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    # Extract body parts
    body_text = ""
    body_html = ""
    payload = msg.get("payload", {})

    def _extract_parts(part: dict):
        nonlocal body_text, body_html
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data", "")

        if data:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                body_text = decoded
            elif mime_type == "text/html":
                body_html = decoded

        for sub_part in part.get("parts", []):
            _extract_parts(sub_part)

    _extract_parts(payload)

    return {
        "id": msg["id"],
        "threadId": msg.get("threadId", ""),
        "sender": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "body_text": body_text,
        "body_html": body_html,
        "snippet": msg.get("snippet", ""),
    }


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def list_calendar_events(
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    max_results: int = 50,
) -> list[dict]:
    """List calendar events in a time range.

    Args:
        time_min: Start of time range in RFC3339 format (e.g. 2026-02-25T00:00:00-05:00).
        time_max: End of time range in RFC3339 format.
        calendar_id: Calendar ID (default: primary).
        max_results: Maximum events to return.

    Returns:
        List of event dicts with id, summary, start, end, attendees, location, etc.
    """
    service = get_calendar_service()

    response = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = response.get("items", [])
    logger.info(f"Fetched {len(events)} calendar events between {time_min} and {time_max}")
    return events


# ---------------------------------------------------------------------------
# Gmail Watch (Pub/Sub push notifications)
# ---------------------------------------------------------------------------

def setup_gmail_watch(user_email: str, topic_name: str) -> dict:
    """Set up Gmail push notifications via Pub/Sub.

    Calls users.watch() to register for push notifications on the user's
    mailbox. The watch expires after ~7 days and must be renewed.

    Args:
        user_email: The Gmail address (API uses 'me' since we auth as this user).
        topic_name: Full Pub/Sub topic name (e.g. projects/my-project/topics/gmail-push).

    Returns:
        Watch response dict with historyId and expiration.
    """
    service = get_gmail_service()

    body = {
        "topicName": topic_name,
        "labelIds": ["INBOX"],
    }

    result = service.users().watch(userId="me", body=body).execute()
    logger.info(
        f"Gmail watch set up for {user_email}: "
        f"historyId={result.get('historyId')}, "
        f"expiration={result.get('expiration')}"
    )
    return result


def get_history(
    user_email: str,
    history_id: str,
    history_types: Optional[list[str]] = None,
) -> dict:
    """Get Gmail history since a given history_id.

    Used to process incremental changes after receiving a Pub/Sub notification.

    Args:
        user_email: The Gmail address (used for logging; API uses 'me').
        history_id: The start history ID (from previous watch or notification).
        history_types: Types of history to return (default: messageAdded).

    Returns:
        History response dict with history list and historyId.
    """
    service = get_gmail_service()

    if history_types is None:
        history_types = ["messageAdded"]

    result = service.users().history().list(
        userId="me",
        startHistoryId=history_id,
        historyTypes=history_types,
        labelId="INBOX",
    ).execute()

    history_records = result.get("history", [])
    logger.debug(
        f"Gmail history for {user_email} since {history_id}: "
        f"{len(history_records)} record(s)"
    )
    return result
