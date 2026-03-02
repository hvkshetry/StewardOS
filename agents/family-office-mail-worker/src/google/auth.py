"""Google OAuth2 authentication helper for Gmail API."""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

_credentials: Credentials | None = None


def _load_credentials() -> Credentials:
    """Load cached credentials and refresh as needed."""
    global _credentials

    if _credentials and _credentials.valid:
        return _credentials

    token_path = Path(settings.google_token_path)
    creds_path = Path(settings.google_credentials_path)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google OAuth token")
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {creds_path}"
                )
            logger.info("Running Google OAuth local consent flow")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json())
        logger.info("Saved Google OAuth token to %s", token_path)

    _credentials = creds
    return _credentials


def get_gmail_service():
    """Return an authenticated Gmail API service."""
    creds = _load_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
