"""Calendar sync-token polling helper.

Used by the scheduler (not a webhook) to detect calendar changes since the
last poll. Google Calendar's incremental sync uses a syncToken that persists
across requests and returns only changed events.
"""

import logging
from typing import Optional

from src.google.auth import get_calendar_service

logger = logging.getLogger(__name__)


def poll_calendar_changes(
    sync_token: Optional[str] = None,
    calendar_id: str = "primary",
) -> dict:
    """Poll for calendar event changes using incremental sync.

    On first call (sync_token=None), performs a full sync to get the initial
    syncToken. On subsequent calls, returns only events that changed since
    the last sync.

    Args:
        sync_token: The nextSyncToken from a previous call, or None for full sync.
        calendar_id: Calendar ID to poll (default: primary).

    Returns:
        Dict with:
            - events: list of changed event dicts
            - next_sync_token: token to use for the next call
    """
    service = get_calendar_service()

    changed_events = []
    page_token = None
    next_sync_token = None

    while True:
        try:
            params = {
                "calendarId": calendar_id,
                "singleEvents": True,
                "showDeleted": True,  # Include cancelled events for awareness
            }

            if sync_token and not page_token:
                # Incremental sync: use syncToken from previous call
                params["syncToken"] = sync_token
            else:
                # Full sync or pagination: use pageToken if available
                if page_token:
                    params["pageToken"] = page_token

            response = service.events().list(**params).execute()

            events = response.get("items", [])
            changed_events.extend(events)

            page_token = response.get("nextPageToken")
            if not page_token:
                # Last page — capture the syncToken for next poll
                next_sync_token = response.get("nextSyncToken", "")
                break

        except Exception as e:
            error_str = str(e)

            # Handle "Sync token is no longer valid" — full re-sync needed
            if "410" in error_str or "fullSyncRequired" in error_str.lower():
                logger.warning(
                    "Calendar sync token expired (410 Gone). "
                    "Performing full re-sync."
                )
                # Recursive call without syncToken triggers full sync
                return poll_calendar_changes(sync_token=None, calendar_id=calendar_id)

            logger.error(f"Calendar sync poll failed: {e}")
            raise

    logger.info(
        f"Calendar poll: {len(changed_events)} changed event(s), "
        f"syncToken={'(new)' if not sync_token else '(incremental)'}"
    )

    return {
        "events": changed_events,
        "next_sync_token": next_sync_token,
    }
