"""Shared Gmail watch renewal and history catch-up logic.

Used by both family-office-mail-worker and family-brief-agent to avoid
duplicating the watch lifecycle management code.
"""

import logging
import time
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)


class WatchStateStore(Protocol):
    """Protocol matching SessionStore.get_watch_state / update_watch_state."""

    async def get_watch_state(self, email: str) -> Optional[dict]: ...
    async def update_watch_state(
        self, email: str, history_id: int, expiration: Optional[int] = None
    ) -> None: ...


async def ensure_watch_if_needed(
    agent_email: str,
    pubsub_topic: str,
    session_store: WatchStateStore,
    setup_gmail_watch: Callable[..., dict],
    renew_lead_seconds: int = 86400,
) -> bool:
    """Renew the Gmail push-notification watch if it is missing or near expiry.

    Args:
        agent_email: The Gmail address being watched.
        pubsub_topic: Full Pub/Sub topic name for users.watch().
        session_store: Any object satisfying the WatchStateStore protocol.
        setup_gmail_watch: Callable ``(user_email, topic_name) -> dict``.
        renew_lead_seconds: Renew when expiration is within this many seconds.

    Returns:
        True if the watch was renewed, False if it was still valid.
    """
    if not pubsub_topic:
        return False

    state = await session_store.get_watch_state(agent_email)
    now_ms = int(time.time() * 1000)
    lead_ms = renew_lead_seconds * 1000

    should_renew = False
    if state is None:
        should_renew = True
    else:
        expiration = state.get("expiration")
        if not expiration or int(expiration) <= now_ms + lead_ms:
            should_renew = True

    if not should_renew:
        return False

    result = setup_gmail_watch(agent_email, pubsub_topic)
    history_id = int(result.get("historyId", 0))
    expiration = int(result.get("expiration", 0)) if result.get("expiration") else None

    await session_store.update_watch_state(
        email=agent_email,
        history_id=history_id,
        expiration=expiration,
    )
    logger.info(
        "Gmail watch renewed for %s: history_id=%s expiration=%s",
        agent_email,
        history_id,
        expiration,
    )
    return True


async def catch_up_missed_history(
    agent_email: str,
    session_store: WatchStateStore,
    get_profile_history_id: Callable[[], int],
    notification_handler: Callable[[dict], None],
    build_pubsub_payload: Callable[[int], dict],
) -> None:
    """Replay missed Gmail history between the stored cursor and the live cursor.

    Args:
        agent_email: The Gmail address being watched.
        session_store: Any object satisfying the WatchStateStore protocol.
        get_profile_history_id: Returns the current mailbox history cursor.
        notification_handler: Async callable that processes a synthetic Pub/Sub payload.
        build_pubsub_payload: Builds the Pub/Sub payload dict from a history ID.
    """
    state = await session_store.get_watch_state(agent_email)
    if not state:
        return

    current_history = int(state["history_id"])
    latest_history = int(get_profile_history_id())

    if latest_history <= current_history:
        return

    logger.info(
        "Detected missed Gmail history range for %s: current=%s latest=%s. Running catch-up.",
        agent_email,
        current_history,
        latest_history,
    )
    await notification_handler(build_pubsub_payload(latest_history))
