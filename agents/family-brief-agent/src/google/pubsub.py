"""Gmail Pub/Sub notification parser.

Gmail push notifications arrive via Google Cloud Pub/Sub. Each notification
contains a base64-encoded JSON payload with the user's email address and
the latest historyId. This module parses and validates those payloads.
"""

import base64
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def parse_pubsub_notification(payload: dict) -> Optional[dict]:
    """Parse a Gmail Pub/Sub push notification.

    Gmail Pub/Sub notifications have this structure:
    {
        "message": {
            "data": "<base64-encoded JSON>",
            "messageId": "...",
            "publishTime": "..."
        },
        "subscription": "projects/.../subscriptions/..."
    }

    The base64-decoded data contains:
    {
        "emailAddress": "user@gmail.com",
        "historyId": 12345
    }

    Args:
        payload: The raw Pub/Sub push notification dict.

    Returns:
        Dict with emailAddress and historyId, or None if parsing fails.
    """
    try:
        message = payload.get("message", {})
        data_b64 = message.get("data", "")

        if not data_b64:
            logger.warning("Pub/Sub notification missing data field")
            return None

        # Decode base64 data
        decoded = base64.urlsafe_b64decode(data_b64).decode("utf-8")
        data = json.loads(decoded)

        email_address = data.get("emailAddress")
        history_id = data.get("historyId")

        if not email_address or not history_id:
            logger.warning(
                f"Pub/Sub data missing required fields: "
                f"emailAddress={email_address}, historyId={history_id}"
            )
            return None

        logger.debug(
            f"Parsed Pub/Sub notification: email={email_address}, historyId={history_id}"
        )
        return {
            "emailAddress": email_address,
            "historyId": int(history_id),
        }

    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Failed to parse Pub/Sub notification: {e}")
        return None


def validate_pubsub_message(payload: dict) -> bool:
    """Validate that a Pub/Sub message is well-formed.

    Performs structural validation:
    - Has a message field with data
    - Has a subscription field (confirms it came through Pub/Sub)
    - Data decodes to valid JSON with expected fields

    Note: For production, also verify the Pub/Sub push endpoint uses HTTPS
    and optionally validate the JWT bearer token in the Authorization header
    using google.auth. This function covers structural validation only.

    Args:
        payload: The raw Pub/Sub push notification dict.

    Returns:
        True if the message passes validation, False otherwise.
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

    # Verify data is valid base64 and contains expected fields
    parsed = parse_pubsub_notification(payload)
    if parsed is None:
        return False

    return True
