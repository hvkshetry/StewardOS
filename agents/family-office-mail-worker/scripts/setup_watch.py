#!/usr/bin/env python3
"""Initialize or renew Gmail watch cursor for family-office worker."""

import asyncio

from src.config import settings
from src.google.client import setup_gmail_watch
from src.session_store import SessionStore


async def main() -> None:
    if not settings.google_pubsub_topic:
        raise SystemExit("GOOGLE_PUBSUB_TOPIC is required")

    result = setup_gmail_watch(settings.google_pubsub_topic)
    history_id = int(result.get("historyId", 0))
    expiration = int(result.get("expiration", 0)) if result.get("expiration") else None

    await SessionStore.initialize()
    await SessionStore.update_watch_state(
        email=settings.agent_email,
        history_id=history_id,
        expiration=expiration,
    )

    print("Watch initialized/renewed")
    print(f"email={settings.agent_email}")
    print(f"history_id={history_id}")
    print(f"expiration={expiration}")


if __name__ == "__main__":
    asyncio.run(main())
