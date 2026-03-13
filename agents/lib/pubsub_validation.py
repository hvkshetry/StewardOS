"""Shared Pub/Sub message parsing and validation.

Extracted from agents/family-office-mail-worker/src/google/pubsub.py so both
the ingress and worker can share the same validation logic.
"""

import base64
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def parse_pubsub_notification(payload: dict) -> Optional[dict]:
    """Parse a Gmail Pub/Sub push notification.

    The base64-decoded data contains:
    {
        "emailAddress": "user@gmail.com",
        "historyId": 12345
    }

    Returns:
        Dict with emailAddress and historyId, or None if parsing fails.
    """
    try:
        message = payload.get("message", {})
        data_b64 = message.get("data", "")

        if not data_b64:
            logger.warning("Pub/Sub notification missing data field")
            return None

        decoded = base64.urlsafe_b64decode(data_b64).decode("utf-8")
        data = json.loads(decoded)

        email_address = data.get("emailAddress")
        history_id = data.get("historyId")

        if not email_address or not history_id:
            logger.warning(
                "Pub/Sub data missing required fields: "
                "emailAddress=%s, historyId=%s",
                email_address,
                history_id,
            )
            return None

        logger.debug(
            "Parsed Pub/Sub notification: email=%s, historyId=%s",
            email_address,
            history_id,
        )
        return {
            "emailAddress": email_address,
            "historyId": int(history_id),
        }

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error("Failed to parse Pub/Sub notification: %s", e)
        return None


def validate_pubsub_message(payload: dict) -> bool:
    """Validate that a Pub/Sub message is well-formed.

    Performs structural validation:
    - Has a message field with data
    - Has a subscription field (confirms it came through Pub/Sub)
    - Data decodes to valid JSON with expected fields
    """
    if not isinstance(payload, dict):
        logger.warning("Pub/Sub payload is not a dict")
        return False

    message = payload.get("message")
    if not isinstance(message, dict):
        logger.warning("Pub/Sub payload missing 'message' dict")
        return False

    if "data" not in message:
        logger.warning("Pub/Sub message missing 'data' field")
        return False

    if "subscription" not in payload:
        logger.warning("Pub/Sub payload missing 'subscription' field")
        return False

    parsed = parse_pubsub_notification(payload)
    if parsed is None:
        return False

    return True
