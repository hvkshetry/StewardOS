"""Gmail notification processing with sender allowlist and alias routing."""

import logging
import re
from datetime import datetime, timezone

from googleapiclient.errors import HttpError
from lib.pubsub_validation import parse_pubsub_notification

from src.config import settings
from src.google.client import get_email_detail, get_history_pages
from src.models import IncomingEmail
from src.session_store import SessionStore

logger = logging.getLogger(__name__)

_MAX_EMAIL_BODY_LENGTH = 10_000

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_ALIAS_RE = re.compile(
    rf"^{re.escape(settings.agent_email.partition('@')[0])}(?:\+([a-z0-9._-]+))?@{re.escape(settings.agent_email.partition('@')[2])}$"
)


def _is_missing_message_error(exc: Exception) -> bool:
    """Return True when Gmail no longer has the history-referenced message."""
    if not isinstance(exc, HttpError):
        return False

    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
    if status != 404:
        return False

    return "notfound" in str(exc).lower() or "requested entity was not found" in str(exc).lower()


def _is_batch_scoped_message_error(exc: Exception) -> bool:
    """Return True when the error likely affects the whole Gmail history batch."""
    if not isinstance(exc, HttpError):
        return False

    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        return False

    return status in {401, 403, 429} or int(status) >= 500


def _extract_email_address(header: str) -> str:
    header = (header or "").strip()
    if "<" in header and ">" in header:
        return header.split("<", 1)[1].split(">", 1)[0].strip().lower()
    match = _EMAIL_RE.search(header)
    return match.group(0).lower() if match else header.lower()


def _is_agent_sender(sender_email: str) -> bool:
    sender = (sender_email or "").lower().strip()
    if sender == settings.agent_email.lower():
        return True

    local, _, domain = settings.agent_email.partition("@")
    if not domain:
        return False

    if not sender.endswith(f"@{domain.lower()}"):
        return False

    sender_local = sender.split("@", 1)[0]
    return sender_local == local.lower() or sender_local.startswith(f"{local.lower()}+")


def _select_alias(recipients: list[str]) -> str:
    known_aliases = set(settings.alias_persona_map.keys())
    for addr in recipients:
        local = addr.lower().strip()
        match = _ALIAS_RE.match(local)
        if not match:
            continue
        alias = match.group(1) or "cos"
        if alias in known_aliases:
            return alias
    return "cos"


async def process_gmail_webhook(
    payload: dict,
    allowed_senders: list[str],
) -> dict:
    """Parse and process one Gmail Pub/Sub notification."""
    notification = parse_pubsub_notification(payload)
    if notification is None:
        raise ValueError("invalid_gmail_notification")

    email_address = notification["emailAddress"]
    new_history_id = int(notification["historyId"])

    watch_state = await SessionStore.get_watch_state(email_address)
    if watch_state is None:
        logger.warning(
            "No watch state for %s. Storing current history id only.",
            email_address,
        )
        await SessionStore.update_watch_state(email_address, new_history_id)
        return {
            "email_address": email_address,
            "history_id": new_history_id,
            "emails": [],
            "cursor_advanced": True,
        }

    last_history_id = str(watch_state["history_id"])

    try:
        history_records = get_history_pages(last_history_id)
    except HttpError as exc:
        status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
        if status == 404:
            logger.warning("History cursor expired; advancing to %s", new_history_id)
            await SessionStore.update_watch_state(email_address, new_history_id)
            return {
                "email_address": email_address,
                "history_id": new_history_id,
                "emails": [],
                "cursor_advanced": True,
            }
        logger.error("Failed to fetch Gmail history: %s", exc)
        raise
    except Exception as exc:
        logger.error("Failed to fetch Gmail history: %s", exc)
        raise

    if not history_records:
        return {
            "email_address": email_address,
            "history_id": new_history_id,
            "emails": [],
            "cursor_advanced": False,
        }

    allowlist = {e.strip().lower() for e in allowed_senders}
    incoming: list[IncomingEmail] = []
    seen_message_ids: set[str] = set()
    warnings: list[str] = []

    for record in history_records:
        for entry in record.get("messagesAdded", []):
            message_id = entry.get("message", {}).get("id", "")
            if not message_id or message_id in seen_message_ids:
                continue
            seen_message_ids.add(message_id)

            try:
                detail = get_email_detail(message_id)
            except Exception as exc:
                if _is_missing_message_error(exc):
                    logger.warning(
                        "Skipping missing Gmail history message %s; it no longer exists.",
                        message_id[:24],
                    )
                    continue
                if _is_batch_scoped_message_error(exc):
                    logger.error(
                        "Aborting Gmail batch due to batch-scoped message detail failure %s: %s",
                        message_id[:24],
                        exc,
                    )
                    raise
                logger.error("Failed fetching message %s: %s", message_id[:24], exc)
                warnings.append(f"message_detail_failed:{message_id}")
                continue

            sender_raw = detail.get("sender", "")
            sender_email = _extract_email_address(sender_raw)
            if _is_agent_sender(sender_email):
                continue

            if sender_email not in allowlist:
                logger.warning("Blocked sender outside allowlist: %s", sender_email)
                continue

            recipients = [r.lower() for r in detail.get("recipients", [])]
            alias = _select_alias(recipients)

            subject = detail.get("subject", "") or "(No subject)"
            body_raw = detail.get("body_text") or detail.get("snippet") or ""
            body = body_raw[:_MAX_EMAIL_BODY_LENGTH]
            message_id_header = detail.get("messageIdHeader") or None
            references = detail.get("references") or None
            in_reply_to = detail.get("inReplyTo") or None

            if references is None and message_id_header:
                references = message_id_header

            incoming.append(
                IncomingEmail(
                    sender=sender_raw,
                    sender_email=sender_email,
                    subject=subject,
                    body=body,
                    message_id=message_id,
                    thread_id=detail.get("threadId") or None,
                    internet_message_id=message_id_header,
                    references_header=references,
                    in_reply_to_header=in_reply_to,
                    recipient_addresses=recipients,
                    target_alias=alias,
                    received_at=datetime.now(timezone.utc),
                )
            )

    return {
        "email_address": email_address,
        "history_id": new_history_id,
        "emails": incoming,
        "cursor_advanced": False,
        "warnings": warnings,
    }
