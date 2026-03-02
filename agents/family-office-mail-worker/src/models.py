"""Data models for family-office mail worker."""

from datetime import datetime
from typing import Optional

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
    received_at: datetime = Field(default_factory=datetime.utcnow)


class SendAck(BaseModel):
    """Required JSON acknowledgment from persona send workflow."""

    status: str
    sent_message_id: str
    thread_id: Optional[str] = None
    from_email: str
    to: str | list[str]


class AgentResponse(BaseModel):
    """Response from a Codex agent invocation."""

    success: bool
    response_text: str
    error: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
