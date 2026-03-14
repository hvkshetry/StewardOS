"""Async state store for thread sessions, idempotency, Gmail watch state, queueing, and case orchestration."""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, or_, select
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP as PG_TIMESTAMP
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import JSON

from src.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

# Dialect-aware column types: use JSONB / TIMESTAMPTZ on Postgres,
# fall back to JSON (TEXT) / DateTime on SQLite.
_JsonVariant = JSON().with_variant(JSONB(), "postgresql")
_TimestampVariant = DateTime().with_variant(PG_TIMESTAMP(timezone=True), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─── Operational Tables (unchanged) ─────────────────────────────────────


class EmailSession(Base):
    """Persists Codex thread sessions keyed by alias+thread."""

    __tablename__ = "email_sessions"

    id = Column(String, primary_key=True)
    session_key = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)


class GmailWatchState(Base):
    """Tracks last history cursor for incremental Gmail sync."""

    __tablename__ = "gmail_watch_state"

    email = Column(String, primary_key=True)
    history_id = Column(BigInteger, nullable=False)
    expiration = Column(BigInteger, nullable=True)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)


class ProcessedGmailMessage(Base):
    """Durable idempotency and delivery status per inbound Gmail message id."""

    __tablename__ = "processed_gmail_messages"

    message_id = Column(String, primary_key=True)
    alias = Column(String, nullable=False)
    thread_id = Column(String, nullable=True)
    sender_email = Column(String, nullable=True)
    status = Column(String, nullable=False)
    sent_message_id = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)


class QueuedGmailNotification(Base):
    """Durable queue for inbound Gmail Pub/Sub notifications."""

    __tablename__ = "queued_gmail_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(String, nullable=False, unique=True, index=True)
    payload_json = Column(Text, nullable=False)
    email = Column(String, nullable=True)
    history_id = Column(BigInteger, nullable=True)
    status = Column(String, nullable=False, index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    claimed_at = Column(_TimestampVariant, nullable=True)
    next_attempt_at = Column(_TimestampVariant, nullable=False, default=_utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)


class ProcessedPlaneDelivery(Base):
    """Idempotency ledger for Plane webhook deliveries."""

    __tablename__ = "processed_plane_deliveries"

    delivery_id = Column(String, primary_key=True)
    created_at = Column(_TimestampVariant, default=_utcnow)


# ─── Unified Case Orchestration Table ───────────────────────────────────
# Replaces: PmSession + CaseSnapshot + EmailThreadCase


class Case(Base):
    """Root orchestration record for a delegation case.

    Unifies PM session tracking, case snapshots, and email-thread linkage
    into a single record with structured_input JSONB for canonical state
    injection (llmenron Experiment 1).
    """

    __tablename__ = "cases"

    case_id = Column(String, primary_key=True)
    session_key = Column(String, nullable=False, unique=True, index=True)
    thread_id = Column(String, nullable=True, index=True)
    lead_alias = Column(String, nullable=False)
    reply_actor = Column(String, nullable=True)
    workspace_slug = Column(String, nullable=False)
    project_id = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    codex_session_id = Column(String, nullable=True)
    # SQLAlchemy JSON handles cross-dialect: JSONB on Postgres, TEXT on SQLite
    structured_input = Column(_JsonVariant, nullable=True)
    structured_result = Column(_JsonVariant, nullable=True)
    last_human_email_body = Column(Text, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)


def _case_to_dict(row: Case) -> dict:
    """Convert a Case ORM row to a plain dict for callers."""
    return {
        "case_id": row.case_id,
        "session_key": row.session_key,
        "thread_id": row.thread_id,
        "lead_alias": row.lead_alias,
        "reply_actor": row.reply_actor,
        "workspace_slug": row.workspace_slug,
        "project_id": row.project_id,
        "status": row.status,
        "codex_session_id": row.codex_session_id,
        "structured_input": row.structured_input,
        "structured_result": row.structured_result,
        "last_human_email_body": row.last_human_email_body,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# ─── Cross-System Identity Graph ──────────────────────────────────────


class WorkItemNode(Base):
    """Canonical internal work object in the identity graph."""

    __tablename__ = "work_item_nodes"

    node_id = Column(String, primary_key=True)
    node_type = Column(String, nullable=False)  # 'case', 'request'
    internal_id = Column(String, nullable=False)
    workspace = Column(String, nullable=True)
    project_id = Column(String, nullable=True)
    title = Column(String, nullable=True)
    status = Column(String, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("node_type", "internal_id", name="uq_work_item_nodes_type_id"),
    )


class ExternalObject(Base):
    """Reference to an object in an external system (Gmail, Paperless, etc.)."""

    __tablename__ = "external_objects"

    ext_id = Column(String, primary_key=True)
    system = Column(String, nullable=False)  # 'gmail', 'paperless', 'sharepoint', 'gdrive'
    system_id = Column(String, nullable=False)
    display_label = Column(String, nullable=True)
    metadata_ = Column("metadata", _JsonVariant, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("system", "system_id", name="uq_external_objects_system_id"),
    )


class Edge(Base):
    """Typed relation between nodes and/or external objects."""

    __tablename__ = "edges"

    edge_id = Column(String, primary_key=True)
    relation_type = Column(String, nullable=False)
    source_node_id = Column(String, ForeignKey("work_item_nodes.node_id"), nullable=True)
    source_ext_id = Column(String, ForeignKey("external_objects.ext_id"), nullable=True)
    target_node_id = Column(String, ForeignKey("work_item_nodes.node_id"), nullable=True)
    target_ext_id = Column(String, ForeignKey("external_objects.ext_id"), nullable=True)
    metadata_ = Column("metadata", _JsonVariant, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "(source_node_id IS NOT NULL AND source_ext_id IS NULL) OR "
            "(source_node_id IS NULL AND source_ext_id IS NOT NULL)",
            name="ck_edge_source_xor",
        ),
        CheckConstraint(
            "(target_node_id IS NOT NULL AND target_ext_id IS NULL) OR "
            "(target_node_id IS NULL AND target_ext_id IS NOT NULL)",
            name="ck_edge_target_xor",
        ),
    )


# ─── Lightweight Request Tier ─────────────────────────────────────────


class Request(Base):
    """Tracked-but-lightweight work that doesn't justify a Plane project."""

    __tablename__ = "requests"

    request_id = Column(String, primary_key=True)
    source_system = Column(String, nullable=False)  # 'gmail', 'plane_webhook', 'scheduled'
    source_object_id = Column(String, nullable=True)
    requester = Column(String, nullable=True)
    assigned_agent = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    urgency = Column(String, default="normal")
    summary = Column(String, nullable=True)
    resolution = Column(String, nullable=True)
    promoted_to_case_id = Column(String, ForeignKey("cases.case_id"), nullable=True)
    thread_id = Column(String, nullable=True)
    created_at = Column(_TimestampVariant, default=_utcnow)
    resolved_at = Column(_TimestampVariant, nullable=True)
    updated_at = Column(_TimestampVariant, default=_utcnow, onupdate=_utcnow)


class SessionStore:
    """Storage helper for thread continuity, idempotency, watch state, and case orchestration."""

    _engine = None
    _session_maker = None

    @staticmethod
    def _utcnow() -> datetime:
        return _utcnow()

    @classmethod
    def _is_postgres(cls) -> bool:
        return cls._engine is not None and cls._engine.dialect.name == "postgresql"

    @classmethod
    async def initialize(cls):
        if cls._engine is None:
            engine_kwargs: dict = {"echo": False}
            # Set search_path for Postgres so tables resolve in the orchestration schema
            if settings.database_url.startswith("postgresql"):
                engine_kwargs["connect_args"] = {
                    "server_settings": {"search_path": "orchestration,public"},
                }
            cls._engine = create_async_engine(settings.database_url, **engine_kwargs)
            cls._session_maker = async_sessionmaker(
                cls._engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with cls._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Session store initialized")

    @classmethod
    async def reset_for_tests(cls):
        if cls._engine is not None:
            await cls._engine.dispose()
        cls._engine = None
        cls._session_maker = None

    # ─── Email Session Methods ───────────────────────────────────────────

    @classmethod
    async def get_session(cls, session_key: str) -> Optional[str]:
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(EmailSession).where(EmailSession.session_key == session_key)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                return row.conversation_id
        return None

    @classmethod
    async def store_session(cls, session_key: str, conversation_id: str):
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(EmailSession).where(EmailSession.session_key == session_key)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row:
                row.conversation_id = conversation_id
                row.updated_at = cls._utcnow()
            else:
                row = EmailSession(
                    id=session_key,
                    session_key=session_key,
                    conversation_id=conversation_id,
                )
                session.add(row)

            await session.commit()

    # ─── Idempotency Methods ────────────────────────────────────────────

    @classmethod
    async def is_message_processed(cls, message_id: str) -> bool:
        """Check if a message has been processed (sent, delegated, or completed maintenance)."""
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(ProcessedGmailMessage).where(ProcessedGmailMessage.message_id == message_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return bool(row and row.status in ("sent", "delegated", "completed"))

    @classmethod
    async def record_message_result(
        cls,
        message_id: str,
        alias: str,
        status: str,
        thread_id: Optional[str] = None,
        sender_email: Optional[str] = None,
        sent_message_id: Optional[str] = None,
        error: Optional[str] = None,
    ):
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(ProcessedGmailMessage).where(ProcessedGmailMessage.message_id == message_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row:
                row.alias = alias
                row.thread_id = thread_id
                row.sender_email = sender_email
                row.status = status
                row.sent_message_id = sent_message_id
                row.error = error
                row.updated_at = cls._utcnow()
            else:
                row = ProcessedGmailMessage(
                    message_id=message_id,
                    alias=alias,
                    thread_id=thread_id,
                    sender_email=sender_email,
                    status=status,
                    sent_message_id=sent_message_id,
                    error=error,
                )
                session.add(row)

            await session.commit()

    @classmethod
    async def get_sent_message_ids_for_thread(cls, thread_id: str, alias: str) -> set[str]:
        """Return sent_message_ids already recorded for a thread+alias (duplicate-reply detection)."""
        await cls.initialize()
        async with cls._session_maker() as session:
            rows = (
                await session.execute(
                    select(ProcessedGmailMessage.sent_message_id)
                    .where(
                        ProcessedGmailMessage.thread_id == thread_id,
                        ProcessedGmailMessage.alias == alias,
                        ProcessedGmailMessage.status == "sent",
                        ProcessedGmailMessage.sent_message_id.is_not(None),
                    )
                )
            ).scalars().all()
            return set(rows)

    # ─── Gmail Watch State ──────────────────────────────────────────────

    @classmethod
    async def get_watch_state(cls, email: str) -> Optional[dict]:
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(GmailWatchState).where(GmailWatchState.email == email)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                return {
                    "history_id": row.history_id,
                    "expiration": row.expiration,
                    "updated_at": row.updated_at,
                }
        return None

    @classmethod
    async def update_watch_state(
        cls,
        email: str,
        history_id: int,
        expiration: Optional[int] = None,
    ):
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(GmailWatchState).where(GmailWatchState.email == email)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row:
                row.history_id = history_id
                if expiration is not None:
                    row.expiration = expiration
                row.updated_at = cls._utcnow()
            else:
                row = GmailWatchState(
                    email=email,
                    history_id=history_id,
                    expiration=expiration,
                )
                session.add(row)

            await session.commit()

    # ─── Gmail Notification Queue ───────────────────────────────────────

    @classmethod
    async def enqueue_gmail_notification(
        cls,
        *,
        event_key: str,
        payload: dict,
        email: str | None = None,
        history_id: int | None = None,
    ) -> dict:
        await cls.initialize()
        serialized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        now = cls._utcnow()
        async with cls._session_maker() as session:
            stmt = select(QueuedGmailNotification).where(QueuedGmailNotification.event_key == event_key)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is not None:
                return {
                    "id": row.id,
                    "event_key": row.event_key,
                    "status": row.status,
                    "duplicate": True,
                    "attempt_count": row.attempt_count,
                }

            row = QueuedGmailNotification(
                event_key=event_key,
                payload_json=serialized_payload,
                email=email,
                history_id=history_id,
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return {
                "id": row.id,
                "event_key": row.event_key,
                "status": row.status,
                "duplicate": False,
                "attempt_count": row.attempt_count,
            }

    @classmethod
    async def claim_next_notification(cls, *, claim_timeout_seconds: int) -> Optional[dict]:
        await cls.initialize()
        now = cls._utcnow()
        stale_cutoff = now - timedelta(seconds=max(1, claim_timeout_seconds))
        async with cls._session_maker() as session:
            stale_stmt = select(QueuedGmailNotification).where(
                QueuedGmailNotification.status == "processing",
                QueuedGmailNotification.claimed_at.is_not(None),
                QueuedGmailNotification.claimed_at < stale_cutoff,
            )
            # Lock stale rows on Postgres to prevent concurrent workers from
            # double-resetting the same timed-out claims.
            if cls._is_postgres():
                stale_stmt = stale_stmt.with_for_update(skip_locked=True)
            stale_rows = (await session.execute(stale_stmt)).scalars().all()
            for row in stale_rows:
                row.status = "failed"
                row.claimed_at = None
                row.last_error = "claim_timeout"
                row.next_attempt_at = now
                row.updated_at = now

            stmt = (
                select(QueuedGmailNotification)
                .where(
                    QueuedGmailNotification.status.in_(("pending", "failed")),
                    QueuedGmailNotification.next_attempt_at <= now,
                )
                .order_by(QueuedGmailNotification.created_at.asc(), QueuedGmailNotification.id.asc())
                .limit(1)
            )
            # Use FOR UPDATE SKIP LOCKED on Postgres for safe concurrent claim
            if cls._is_postgres():
                stmt = stmt.with_for_update(skip_locked=True)

            row = (await session.execute(stmt)).scalars().first()
            if row is None:
                await session.commit()
                return None

            row.status = "processing"
            row.attempt_count = int(row.attempt_count or 0) + 1
            row.claimed_at = now
            row.updated_at = now
            await session.commit()
            return {
                "id": row.id,
                "event_key": row.event_key,
                "payload": json.loads(row.payload_json),
                "email": row.email,
                "history_id": row.history_id,
                "status": row.status,
                "attempt_count": row.attempt_count,
            }

    @classmethod
    async def mark_notification_completed(cls, notification_id: int) -> None:
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            stmt = select(QueuedGmailNotification).where(QueuedGmailNotification.id == notification_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return
            row.status = "completed"
            row.claimed_at = None
            row.last_error = None
            row.updated_at = now
            await session.commit()

    @classmethod
    async def mark_notification_failed(
        cls,
        notification_id: int,
        *,
        error: str,
        retry_delay_seconds: int,
    ) -> None:
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            stmt = select(QueuedGmailNotification).where(QueuedGmailNotification.id == notification_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return
            row.status = "failed"
            row.claimed_at = None
            row.last_error = error[:2000]
            row.next_attempt_at = now + timedelta(seconds=max(1, retry_delay_seconds))
            row.updated_at = now
            await session.commit()

    @classmethod
    async def get_notification_status(cls, notification_id: int) -> Optional[dict]:
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(QueuedGmailNotification).where(QueuedGmailNotification.id == notification_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "event_key": row.event_key,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "last_error": row.last_error,
            }

    # ─── Plane Delivery Idempotency ─────────────────────────────────────

    @classmethod
    async def is_plane_delivery_processed(cls, delivery_id: str) -> bool:
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(ProcessedPlaneDelivery).where(
                        ProcessedPlaneDelivery.delivery_id == delivery_id
                    )
                )
            ).scalar_one_or_none()
            return row is not None

    @classmethod
    async def record_plane_delivery(cls, delivery_id: str) -> None:
        await cls.initialize()
        try:
            async with cls._session_maker() as session:
                session.add(ProcessedPlaneDelivery(delivery_id=delivery_id))
                await session.commit()
        except IntegrityError:
            pass  # Concurrent webhook/poller already inserted this delivery

    # ─── Unified Case Orchestration ─────────────────────────────────────

    @classmethod
    async def upsert_case(
        cls,
        *,
        case_id: str,
        session_key: str,
        workspace_slug: str,
        project_id: str,
        lead_alias: str,
        thread_id: str | None = None,
        reply_actor: str | None = None,
        codex_session_id: str | None = None,
        structured_input: dict | None = None,
        structured_result: dict | None = None,
        last_human_email_body: str | None = None,
    ) -> dict:
        """Create or reactivate a case record.

        If a case exists on this session_key and is closed, reactivate with
        new case data (second delegation on same thread). If active, return
        duplicate.
        """
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            # Check for existing case on same session_key
            existing = (
                await session.execute(
                    select(Case).where(Case.session_key == session_key)
                )
            ).scalar_one_or_none()

            if existing is not None:
                if existing.status == "closed":
                    # Reactivate with new case data (second delegation on same thread)
                    existing.case_id = case_id
                    existing.workspace_slug = workspace_slug
                    existing.project_id = project_id
                    existing.lead_alias = lead_alias
                    existing.thread_id = thread_id
                    existing.reply_actor = reply_actor or lead_alias
                    existing.status = "active"
                    existing.codex_session_id = codex_session_id
                    existing.structured_input = structured_input
                    existing.structured_result = structured_result
                    existing.last_human_email_body = last_human_email_body
                    existing.updated_at = now
                    await session.commit()
                    return {
                        "case_id": case_id,
                        "duplicate": False,
                    }
                return {
                    "case_id": existing.case_id,
                    "duplicate": True,
                }

            row = Case(
                case_id=case_id,
                session_key=session_key,
                thread_id=thread_id,
                lead_alias=lead_alias,
                reply_actor=reply_actor or lead_alias,
                workspace_slug=workspace_slug,
                project_id=project_id,
                codex_session_id=codex_session_id,
                structured_input=structured_input,
                structured_result=structured_result,
                last_human_email_body=last_human_email_body,
            )
            session.add(row)
            await session.commit()
            return {
                "case_id": row.case_id,
                "duplicate": False,
            }

    @classmethod
    async def update_case(
        cls,
        case_id: str,
        *,
        structured_input: dict | None = ...,
        structured_result: dict | None = ...,
        last_human_email_body: str | None = ...,
        reply_actor: str | None = ...,
        codex_session_id: str | None = ...,
    ) -> None:
        """Update specific fields on an existing case. Use sentinel ... to skip a field."""
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Case).where(Case.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            if structured_input is not ...:
                row.structured_input = structured_input
            if structured_result is not ...:
                row.structured_result = structured_result
            if last_human_email_body is not ...:
                row.last_human_email_body = last_human_email_body
            if reply_actor is not ...:
                row.reply_actor = reply_actor
            if codex_session_id is not ...:
                row.codex_session_id = codex_session_id
            row.updated_at = now
            await session.commit()

    @classmethod
    async def get_case(cls, case_id: str) -> Optional[dict]:
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Case).where(Case.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return _case_to_dict(row)

    @classmethod
    async def get_case_by_thread(cls, thread_id: str) -> Optional[dict]:
        """Look up the most recently created active case for a Gmail thread.

        When multiple cases exist (e.g. successive delegations on the same
        thread), returns the most recently created one.
        """
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Case)
                    .where(Case.thread_id == thread_id, Case.status == "active")
                    .order_by(Case.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if row is None:
                return None
            return _case_to_dict(row)

    @classmethod
    async def close_case(cls, case_id: str) -> None:
        """Mark a case as closed when all delegated tasks are complete."""
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Case).where(Case.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is not None and row.status == "active":
                row.status = "closed"
                row.updated_at = cls._utcnow()
                await session.commit()

    @classmethod
    async def get_active_case_workspaces(cls) -> list[str]:
        """Return distinct workspace slugs with active cases."""
        await cls.initialize()
        async with cls._session_maker() as session:
            rows = (
                await session.execute(
                    select(Case.workspace_slug)
                    .where(Case.status == "active")
                    .distinct()
                )
            ).scalars().all()
            return list(rows)

    @classmethod
    async def get_active_case_project_ids(cls, workspace_slug: str) -> list[str]:
        """Return distinct project IDs with active cases in a workspace."""
        await cls.initialize()
        async with cls._session_maker() as session:
            rows = (
                await session.execute(
                    select(Case.project_id)
                    .where(
                        Case.workspace_slug == workspace_slug,
                        Case.status == "active",
                    )
                    .distinct()
                )
            ).scalars().all()
            return list(rows)

    # ─── Cross-System Identity Graph ───────────────────────────────────

    @classmethod
    async def register_node(
        cls,
        node_type: str,
        internal_id: str,
        *,
        workspace: str | None = None,
        project_id: str | None = None,
        title: str | None = None,
        status: str | None = None,
    ) -> str:
        """Upsert a WorkItemNode on (node_type, internal_id). Returns node_id.

        Handles concurrent insert races via IntegrityError retry.
        """
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            existing = (
                await session.execute(
                    select(WorkItemNode).where(
                        WorkItemNode.node_type == node_type,
                        WorkItemNode.internal_id == internal_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                if workspace is not None:
                    existing.workspace = workspace
                if project_id is not None:
                    existing.project_id = project_id
                if title is not None:
                    existing.title = title
                if status is not None:
                    existing.status = status
                existing.updated_at = now
                await session.commit()
                return existing.node_id

            node_id = str(uuid.uuid4())
            session.add(WorkItemNode(
                node_id=node_id,
                node_type=node_type,
                internal_id=internal_id,
                workspace=workspace,
                project_id=project_id,
                title=title,
                status=status,
            ))
            try:
                await session.commit()
                return node_id
            except IntegrityError:
                await session.rollback()

        # Concurrent insert won — re-read the winner's row
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(WorkItemNode).where(
                        WorkItemNode.node_type == node_type,
                        WorkItemNode.internal_id == internal_id,
                    )
                )
            ).scalar_one()
            return row.node_id

    @classmethod
    async def register_external_object(
        cls,
        system: str,
        system_id: str,
        *,
        display_label: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Upsert an ExternalObject on (system, system_id). Returns ext_id.

        Handles concurrent insert races via IntegrityError retry.
        """
        await cls.initialize()
        async with cls._session_maker() as session:
            existing = (
                await session.execute(
                    select(ExternalObject).where(
                        ExternalObject.system == system,
                        ExternalObject.system_id == system_id,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                if display_label is not None:
                    existing.display_label = display_label
                if metadata is not None:
                    existing.metadata_ = metadata
                await session.commit()
                return existing.ext_id

            ext_id = str(uuid.uuid4())
            session.add(ExternalObject(
                ext_id=ext_id,
                system=system,
                system_id=system_id,
                display_label=display_label,
                metadata_=metadata,
            ))
            try:
                await session.commit()
                return ext_id
            except IntegrityError:
                await session.rollback()

        # Concurrent insert won — re-read the winner's row
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(ExternalObject).where(
                        ExternalObject.system == system,
                        ExternalObject.system_id == system_id,
                    )
                )
            ).scalar_one()
            return row.ext_id

    @classmethod
    async def create_edge(
        cls,
        relation_type: str,
        *,
        source_node_id: str | None = None,
        source_ext_id: str | None = None,
        target_node_id: str | None = None,
        target_ext_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Create an edge. Validates exactly one source and one target. Returns edge_id."""
        if bool(source_node_id) == bool(source_ext_id):
            raise ValueError("Exactly one of source_node_id or source_ext_id must be provided")
        if bool(target_node_id) == bool(target_ext_id):
            raise ValueError("Exactly one of target_node_id or target_ext_id must be provided")

        await cls.initialize()
        edge_id = str(uuid.uuid4())
        async with cls._session_maker() as session:
            session.add(Edge(
                edge_id=edge_id,
                relation_type=relation_type,
                source_node_id=source_node_id,
                source_ext_id=source_ext_id,
                target_node_id=target_node_id,
                target_ext_id=target_ext_id,
                metadata_=metadata,
            ))
            await session.commit()
            return edge_id

    @classmethod
    async def get_edges_for_node(cls, node_id: str) -> list[dict]:
        """All edges where node is source or target, with linked object data."""
        await cls.initialize()
        async with cls._session_maker() as session:
            rows = (
                await session.execute(
                    select(Edge).where(
                        or_(
                            Edge.source_node_id == node_id,
                            Edge.target_node_id == node_id,
                        )
                    )
                )
            ).scalars().all()

            results = []
            for e in rows:
                entry: dict = {
                    "edge_id": e.edge_id,
                    "relation_type": e.relation_type,
                    "source_node_id": e.source_node_id,
                    "source_ext_id": e.source_ext_id,
                    "target_node_id": e.target_node_id,
                    "target_ext_id": e.target_ext_id,
                    "metadata": e.metadata_,
                    "created_at": e.created_at,
                }
                # Resolve linked objects
                if e.source_node_id and e.source_node_id != node_id:
                    src = (await session.execute(
                        select(WorkItemNode).where(WorkItemNode.node_id == e.source_node_id)
                    )).scalar_one_or_none()
                    if src:
                        entry["source_node"] = {"node_id": src.node_id, "node_type": src.node_type,
                                                "internal_id": src.internal_id, "title": src.title, "status": src.status}
                if e.target_node_id and e.target_node_id != node_id:
                    tgt = (await session.execute(
                        select(WorkItemNode).where(WorkItemNode.node_id == e.target_node_id)
                    )).scalar_one_or_none()
                    if tgt:
                        entry["target_node"] = {"node_id": tgt.node_id, "node_type": tgt.node_type,
                                                "internal_id": tgt.internal_id, "title": tgt.title, "status": tgt.status}
                if e.source_ext_id:
                    ext = (await session.execute(
                        select(ExternalObject).where(ExternalObject.ext_id == e.source_ext_id)
                    )).scalar_one_or_none()
                    if ext:
                        entry["source_ext"] = {"ext_id": ext.ext_id, "system": ext.system,
                                               "system_id": ext.system_id, "display_label": ext.display_label}
                if e.target_ext_id:
                    ext = (await session.execute(
                        select(ExternalObject).where(ExternalObject.ext_id == e.target_ext_id)
                    )).scalar_one_or_none()
                    if ext:
                        entry["target_ext"] = {"ext_id": ext.ext_id, "system": ext.system,
                                               "system_id": ext.system_id, "display_label": ext.display_label}
                results.append(entry)
            return results

    @classmethod
    async def get_node_by_internal_id(cls, node_type: str, internal_id: str) -> dict | None:
        """Lookup node by natural key."""
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(WorkItemNode).where(
                        WorkItemNode.node_type == node_type,
                        WorkItemNode.internal_id == internal_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "node_id": row.node_id,
                "node_type": row.node_type,
                "internal_id": row.internal_id,
                "workspace": row.workspace,
                "project_id": row.project_id,
                "title": row.title,
                "status": row.status,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    @classmethod
    async def _edge_exists(
        cls,
        relation_type: str,
        *,
        source_node_id: str | None = None,
        source_ext_id: str | None = None,
        target_node_id: str | None = None,
        target_ext_id: str | None = None,
    ) -> bool:
        """Check if an edge with matching relation/source/target already exists."""
        await cls.initialize()
        async with cls._session_maker() as session:
            conditions = [Edge.relation_type == relation_type]
            if source_node_id:
                conditions.append(Edge.source_node_id == source_node_id)
            else:
                conditions.append(Edge.source_ext_id == source_ext_id)
            if target_node_id:
                conditions.append(Edge.target_node_id == target_node_id)
            else:
                conditions.append(Edge.target_ext_id == target_ext_id)
            row = (await session.execute(select(Edge).where(*conditions).limit(1))).scalar_one_or_none()
            return row is not None

    @classmethod
    async def _register_case_graph(
        cls,
        case_id: str,
        thread_id: str | None,
        message_id: str | None,
        workspace_slug: str | None,
        project_id: str | None,
        title: str | None,
    ) -> None:
        """Register a Case in the identity graph with optional Gmail linkage.

        Failure-isolated: logs errors but never re-raises.
        """
        try:
            node_id = await cls.register_node(
                "case",
                case_id,
                workspace=workspace_slug,
                project_id=project_id,
                title=title,
                status="active",
            )
            if thread_id:
                ext_id = await cls.register_external_object(
                    "gmail",
                    thread_id,
                    display_label=f"Gmail thread {thread_id[:12]}",
                )
                if not await cls._edge_exists(
                    "spawned_from", source_node_id=node_id, target_ext_id=ext_id,
                ):
                    await cls.create_edge(
                        "spawned_from",
                        source_node_id=node_id,
                        target_ext_id=ext_id,
                    )
        except Exception:
            logger.warning(
                "Graph registration failed for case %s", case_id[:24], exc_info=True,
            )

    # ─── Lightweight Request Tier ──────────────────────────────────────

    @classmethod
    async def create_request(
        cls,
        *,
        source_system: str,
        assigned_agent: str,
        requester: str | None = None,
        source_object_id: str | None = None,
        summary: str | None = None,
        urgency: str = "normal",
        thread_id: str | None = None,
    ) -> dict:
        """Create a Request + register graph node + external object edge."""
        await cls.initialize()
        request_id = str(uuid.uuid4())
        now = cls._utcnow()
        async with cls._session_maker() as session:
            session.add(Request(
                request_id=request_id,
                source_system=source_system,
                source_object_id=source_object_id,
                requester=requester,
                assigned_agent=assigned_agent,
                status="open",
                urgency=urgency,
                summary=summary,
                thread_id=thread_id,
                created_at=now,
                updated_at=now,
            ))
            await session.commit()

        # Graph registration (failure-isolated)
        try:
            node_id = await cls.register_node(
                "request",
                request_id,
                title=summary,
                status="open",
            )
            if thread_id:
                ext_id = await cls.register_external_object(
                    "gmail",
                    thread_id,
                    display_label=f"Gmail thread {thread_id[:12]}",
                )
                if not await cls._edge_exists(
                    "spawned_from", source_node_id=node_id, target_ext_id=ext_id,
                ):
                    await cls.create_edge(
                        "spawned_from",
                        source_node_id=node_id,
                        target_ext_id=ext_id,
                    )
        except Exception:
            logger.debug(
                "Graph registration failed for request %s", request_id[:24], exc_info=True,
            )

        return {
            "request_id": request_id,
            "status": "open",
            "assigned_agent": assigned_agent,
            "summary": summary,
        }

    @classmethod
    async def resolve_request(cls, request_id: str, resolution: str | None = None) -> None:
        """Set status='resolved', resolved_at=now, update node status."""
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Request).where(Request.request_id == request_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = "resolved"
            row.resolution = resolution
            row.resolved_at = now
            row.updated_at = now
            await session.commit()

        # Update graph node status (failure-isolated)
        try:
            await cls.register_node("request", request_id, status="resolved")
        except Exception:
            logger.debug("Graph node status update failed for request %s", request_id[:24], exc_info=True)

    @classmethod
    async def promote_request(cls, request_id: str, case_id: str) -> None:
        """Promote request to a case. Creates 'promoted_to' edge."""
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Request).where(Request.request_id == request_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = "promoted"
            row.promoted_to_case_id = case_id
            row.updated_at = now
            await session.commit()

        # Graph: ensure nodes exist, then create request→case edge (failure-isolated)
        try:
            req_node_id = await cls.register_node("request", request_id, status="promoted")
            case_node_id = await cls.register_node("case", case_id)
            if not await cls._edge_exists(
                "promoted_to",
                source_node_id=req_node_id,
                target_node_id=case_node_id,
            ):
                await cls.create_edge(
                    "promoted_to",
                    source_node_id=req_node_id,
                    target_node_id=case_node_id,
                )
        except Exception:
            logger.debug("Graph promotion edge failed for request %s", request_id[:24], exc_info=True)

    @classmethod
    async def get_request(cls, request_id: str) -> dict | None:
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(Request).where(Request.request_id == request_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "request_id": row.request_id,
                "source_system": row.source_system,
                "source_object_id": row.source_object_id,
                "requester": row.requester,
                "assigned_agent": row.assigned_agent,
                "status": row.status,
                "urgency": row.urgency,
                "summary": row.summary,
                "resolution": row.resolution,
                "promoted_to_case_id": row.promoted_to_case_id,
                "thread_id": row.thread_id,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
                "updated_at": row.updated_at,
            }

    @classmethod
    async def get_open_requests(cls, assigned_agent: str | None = None) -> list[dict]:
        """All open requests, optionally filtered by agent."""
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(Request).where(Request.status == "open")
            if assigned_agent is not None:
                stmt = stmt.where(Request.assigned_agent == assigned_agent)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "request_id": r.request_id,
                    "source_system": r.source_system,
                    "requester": r.requester,
                    "assigned_agent": r.assigned_agent,
                    "summary": r.summary,
                    "urgency": r.urgency,
                    "thread_id": r.thread_id,
                    "created_at": r.created_at,
                }
                for r in rows
            ]
