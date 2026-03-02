"""Gmail webhook handler with sender allowlist.

Processes Gmail Pub/Sub push notifications by:
1. Parsing the Pub/Sub notification to get historyId
2. Fetching history since the last known historyId
3. For each new message, checking the sender against the family_emails allowlist
4. Non-family senders are silently discarded (logged at DEBUG)
5. Family senders produce an IncomingEmail for further processing
"""

import logging
import time
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from src.config import settings
from src.google.pubsub import parse_pubsub_notification
from src.google.client import get_history, get_email_detail
from src.models import IncomingEmail
from src.session_store import SessionStore

logger = logging.getLogger(__name__)

# Deduplication: track recently processed message IDs
_recent_message_ids: OrderedDict[str, float] = OrderedDict()
_DEDUP_MAX_SIZE = 200
_DEDUP_TTL_SECONDS = 120


def _is_duplicate(message_id: str) -> bool:
    """Check if this message ID was recently processed."""
    now = time.monotonic()

    # Evict expired entries
    while _recent_message_ids:
        oldest_key, oldest_time = next(iter(_recent_message_ids.items()))
        if now - oldest_time > _DEDUP_TTL_SECONDS:
            _recent_message_ids.pop(oldest_key)
        else:
            break

    if message_id in _recent_message_ids:
        return True

    _recent_message_ids[message_id] = now

    while len(_recent_message_ids) > _DEDUP_MAX_SIZE:
        _recent_message_ids.popitem(last=False)

    return False


_MAX_EMAIL_BODY_LENGTH = 10_000


def _extract_email_address(from_header: str) -> str:
    """Extract bare email address from a From header.

    Handles formats like:
        "Jane Doe <jane@example.com>"
        "jane@example.com"
        "<jane@example.com>"
    """
    from_header = from_header.strip()
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].strip().lower()
    return from_header.strip().lower()


async def process_gmail_webhook(
    payload: dict,
    family_emails: list[str],
) -> Optional[IncomingEmail]:
    """Process a Gmail Pub/Sub notification with sender allowlist enforcement.

    Args:
        payload: Raw Pub/Sub push notification payload.
        family_emails: List of allowlisted email addresses (lowercase).

    Returns:
        IncomingEmail if the sender is in the allowlist, None otherwise.
    """
    # Parse Pub/Sub notification
    notification = parse_pubsub_notification(payload)
    if notification is None:
        logger.warning("Failed to parse Gmail Pub/Sub notification")
        return None

    email_address = notification["emailAddress"]
    new_history_id = notification["historyId"]

    logger.info(
        f"Gmail notification for {email_address}: historyId={new_history_id}"
    )

    # Get the last known history_id from the session store
    watch_state = await SessionStore.get_watch_state(email_address)
    if watch_state is None:
        logger.warning(
            f"No watch state for {email_address} — cannot fetch history. "
            "Saving current historyId for future notifications."
        )
        await SessionStore.update_watch_state(email_address, new_history_id)
        return None

    last_history_id = str(watch_state["history_id"])

    # Fetch history since last known point
    try:
        history_response = get_history(email_address, last_history_id)
    except Exception as e:
        logger.error(f"Failed to fetch Gmail history for {email_address}: {e}")
        # Update history_id anyway to avoid re-processing on next notification
        await SessionStore.update_watch_state(email_address, new_history_id)
        return None

    # Update stored history_id
    await SessionStore.update_watch_state(email_address, new_history_id)

    # Extract new message IDs from history
    history_records = history_response.get("history", [])
    if not history_records:
        logger.debug(f"No new history records for {email_address}")
        return None

    # Normalize allowlist for comparison
    allowlist = {e.strip().lower() for e in family_emails}

    # Process each new message in history
    for record in history_records:
        messages_added = record.get("messagesAdded", [])

        for msg_entry in messages_added:
            msg_meta = msg_entry.get("message", {})
            message_id = msg_meta.get("id", "")

            if not message_id:
                continue

            # Dedup: skip if we recently processed this message
            if _is_duplicate(message_id):
                logger.debug(f"Skipping duplicate message {message_id[:20]}...")
                continue

            # Fetch full email details to check sender
            try:
                email_detail = get_email_detail(email_address, message_id)
            except Exception as e:
                logger.error(f"Failed to fetch email {message_id[:20]}: {e}")
                continue

            sender_raw = email_detail.get("sender", "")
            sender_email = _extract_email_address(sender_raw)

            # Skip emails sent by the agent itself
            if sender_email == settings.agent_email.lower():
                logger.debug(f"Skipping self-sent email: {email_detail.get('subject', '')}")
                continue

            # SENDER ALLOWLIST CHECK — the core security boundary
            if sender_email not in allowlist:
                logger.debug(
                    f"Discarding email from non-family sender: {sender_email} "
                    f"(subject: {email_detail.get('subject', '')[:60]})"
                )
                continue

            # Sender is in family allowlist — create IncomingEmail
            subject = email_detail.get("subject", "(No subject)")
            raw_body = email_detail.get("body_text", "") or email_detail.get("snippet", "")
            body = raw_body[:_MAX_EMAIL_BODY_LENGTH] if len(raw_body) > _MAX_EMAIL_BODY_LENGTH else raw_body
            thread_id = email_detail.get("threadId", "")

            logger.info(
                f"Family email from {sender_raw}: {subject} "
                f"(message_id={message_id[:20]}...)"
            )

            return IncomingEmail(
                sender=sender_raw,
                subject=subject,
                body=body,
                message_id=message_id,
                thread_id=thread_id or None,
                received_at=datetime.utcnow(),
            )

    logger.debug("No family emails found in this notification batch")
    return None
