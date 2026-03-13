"""Data models for family-office mail worker."""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class IncomingEmail(BaseModel):
    """Incoming email parsed from Gmail history."""

    sender: str
    sender_email: str
    subject: str
    body: str
    message_id: str
    thread_id: Optional[str] = None
    internet_message_id: Optional[str] = None
    references_header: Optional[str] = None
    in_reply_to_header: Optional[str] = None
    recipient_addresses: list[str] = Field(default_factory=list)
    target_alias: str = "cos"
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionAck(BaseModel):
    """Unified acknowledgment envelope for all persona action types.

    All personas return ACTION_ACK_JSON:{...} as their terminal output.
    """

    action: Literal["reply", "delegate", "maintenance"]

    # For action=reply:
    sent_message_id: str | None = None
    thread_id: str | None = None
    from_email: str | None = None
    to: str | list[str] | None = None

    # For action=delegate (persona creates Plane items via plane-pm directly):
    case_id: str | None = None
    project_id: str | None = None
    human_update_html: str | None = None

    # For action=maintenance:
    operation: str | None = None
    summary: str | None = None
    ingestion_run_ids: list[int] = Field(default_factory=list)
    records_written: int | None = None
    details: dict = Field(default_factory=dict)

    # Common:
    status: str = "ok"


class AgentResponse(BaseModel):
    """Response from a Codex agent invocation."""

    success: bool
    response_text: str
    error: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
