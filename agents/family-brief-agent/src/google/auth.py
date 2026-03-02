"""Google OAuth2 authentication helper.

Loads credentials from the token file, refreshes if expired, and provides
authenticated service objects for Gmail and Calendar APIs.
"""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import settings

logger = logging.getLogger(__name__)

# Scopes required by the family brief agent:
#   - gmail.modify: read emails, send emails, manage labels
#   - calendar.readonly: list events (agent doesn't create events)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]

_credentials: Credentials | None = None


def _load_credentials() -> Credentials:
    """Load and cache Google OAuth2 credentials.

    On first call, reads the token file. If the token is expired, refreshes it
    and writes the updated token back to disk. If no token file exists, runs
    the interactive OAuth2 consent flow (only needed once during setup).
    """
    global _credentials

    if _credentials and _credentials.valid:
        return _credentials

    token_path = Path(settings.google_token_path)
    creds_path = Path(settings.google_credentials_path)

    creds = None

    # Try loading existing token
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # Refresh or run consent flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google OAuth2 token")
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {creds_path}. "
                    "Download OAuth2 client credentials from Google Cloud Console."
                )
            logger.info("Running Google OAuth2 consent flow (first-time setup)")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Persist refreshed/new token
        token_path.write_text(creds.to_json())
        logger.info(f"Google OAuth2 token saved to {token_path}")

    _credentials = creds
    return _credentials


def get_gmail_service():
    """Return an authenticated Gmail API service object.

    Usage:
        service = get_gmail_service()
        results = service.users().messages().list(userId="me").execute()
    """
    creds = _load_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def get_calendar_service():
    """Return an authenticated Google Calendar API service object.

    Usage:
        service = get_calendar_service()
        events = service.events().list(calendarId="primary").execute()
    """
    creds = _load_credentials()
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
