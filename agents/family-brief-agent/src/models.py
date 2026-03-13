"""Data models for family brief agent."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IncomingEmail(BaseModel):
    """Incoming email parsed from Gmail notification."""

    sender: str
    subject: str
    body: str
    message_id: str
    thread_id: Optional[str] = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentResponse(BaseModel):
    """Response from a Codex agent call."""

    success: bool
    response_text: str
    error: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ScheduledJob(str, Enum):
    """Scheduled job types."""

    DAILY_BRIEF = "daily_brief"
    PRE_MEETING = "pre_meeting"
    WEEKLY_DIGEST = "weekly_digest"
    GMAIL_WATCH_RENEWAL = "gmail_watch_renewal"
