"""Async SQLite state store for thread sessions, idempotency, Gmail watch state, queueing, and PM sessions."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class EmailSession(Base):
    """Persists Codex thread sessions keyed by alias+thread."""

    __tablename__ = "email_sessions"

    id = Column(String, primary_key=True)
    session_key = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class GmailWatchState(Base):
    """Tracks last history cursor for incremental Gmail sync."""

    __tablename__ = "gmail_watch_state"

    email = Column(String, primary_key=True)
    history_id = Column(BigInteger, nullable=False)
    expiration = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


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
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


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
    claimed_at = Column(DateTime, nullable=True)
    next_attempt_at = Column(DateTime, nullable=False, default=_utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


# ─── Plane PM Session Tables ────────────────────────────────────────────────


class PmSession(Base):
    """Maps a session_key (gmail thread) to a Plane case for PM tracking."""

    __tablename__ = "pm_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_key = Column(String, nullable=False, unique=True, index=True)
    case_id = Column(String, nullable=False, index=True)
    workspace_slug = Column(String, nullable=False)
    project_id = Column(String, nullable=False)
    lead_alias = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)



class ProcessedPlaneDelivery(Base):
    """Idempotency ledger for Plane webhook deliveries."""

    __tablename__ = "processed_plane_deliveries"

    delivery_id = Column(String, primary_key=True)
    created_at = Column(DateTime, default=_utcnow)


class EmailThreadCase(Base):
    """Links a Gmail thread_id to a Plane case_id for email resume."""

    __tablename__ = "email_thread_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    thread_id = Column(String, nullable=False, index=True)
    case_id = Column(String, nullable=False, index=True)
    workspace_slug = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class CaseSnapshot(Base):
    """Durable resume snapshot for Plane cases (survives Codex session TTL)."""

    __tablename__ = "case_snapshots"

    case_id = Column(String, primary_key=True)
    condensed_context = Column(Text, nullable=True)
    last_human_email_body = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)



class SessionStore:
    """Storage helper for thread continuity, idempotency, and watch state."""

    _engine = None
    _session_maker = None

    @staticmethod
    def _utcnow() -> datetime:
        return _utcnow()

    @classmethod
    async def initialize(cls):
        if cls._engine is None:
            cls._engine = create_async_engine(settings.database_url, echo=False)
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

    # ─── Plane PM Session Methods ────────────────────────────────────────────

    @classmethod
    async def create_pm_session(
        cls,
        *,
        session_key: str,
        case_id: str,
        workspace_slug: str,
        project_id: str,
        lead_alias: str,
    ) -> dict:
        await cls.initialize()
        async with cls._session_maker() as session:
            existing = (
                await session.execute(
                    select(PmSession).where(PmSession.session_key == session_key)
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.status == "closed":
                    # Reactivate with new case data (second delegation on same thread)
                    existing.case_id = case_id
                    existing.workspace_slug = workspace_slug
                    existing.project_id = project_id
                    existing.lead_alias = lead_alias
                    existing.status = "active"
                    existing.updated_at = cls._utcnow()
                    await session.commit()
                    return {
                        "id": existing.id,
                        "case_id": case_id,
                        "duplicate": False,
                    }
                return {
                    "id": existing.id,
                    "case_id": existing.case_id,
                    "duplicate": True,
                }

            row = PmSession(
                session_key=session_key,
                case_id=case_id,
                workspace_slug=workspace_slug,
                project_id=project_id,
                lead_alias=lead_alias,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return {
                "id": row.id,
                "case_id": row.case_id,
                "duplicate": False,
            }

    @classmethod
    async def get_pm_session_by_case(cls, case_id: str) -> Optional[dict]:
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(PmSession).where(PmSession.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "session_key": row.session_key,
                "case_id": row.case_id,
                "workspace_slug": row.workspace_slug,
                "project_id": row.project_id,
                "lead_alias": row.lead_alias,
                "status": row.status,
            }

    @classmethod
    async def get_pm_session_by_thread(cls, thread_id: str) -> Optional[dict]:
        """Look up PM session via email_thread_cases → pm_sessions.

        When multiple links exist (e.g. successive delegations on the same
        thread), returns the most recently created link's PM session.
        """
        await cls.initialize()
        async with cls._session_maker() as session:
            link = (
                await session.execute(
                    select(EmailThreadCase)
                    .where(EmailThreadCase.thread_id == thread_id)
                    .order_by(EmailThreadCase.created_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if link is None:
                return None
            row = (
                await session.execute(
                    select(PmSession).where(PmSession.case_id == link.case_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "id": row.id,
                "session_key": row.session_key,
                "case_id": row.case_id,
                "workspace_slug": row.workspace_slug,
                "project_id": row.project_id,
                "lead_alias": row.lead_alias,
                "status": row.status,
            }

    @classmethod
    async def close_pm_session(cls, case_id: str) -> None:
        """Mark a PM session as closed when all delegated tasks are complete."""
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(PmSession).where(PmSession.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is not None and row.status == "active":
                row.status = "closed"
                await session.commit()

    @classmethod
    async def link_thread_to_case(cls, *, thread_id: str, case_id: str, workspace_slug: str) -> None:
        await cls.initialize()
        async with cls._session_maker() as session:
            existing = (
                await session.execute(
                    select(EmailThreadCase).where(
                        EmailThreadCase.thread_id == thread_id,
                        EmailThreadCase.case_id == case_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(EmailThreadCase(
                thread_id=thread_id,
                case_id=case_id,
                workspace_slug=workspace_slug,
            ))
            await session.commit()

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

    @classmethod
    async def upsert_case_snapshot(
        cls,
        *,
        case_id: str,
        condensed_context: str | None = None,
        last_human_email_body: str | None = None,
    ) -> None:
        await cls.initialize()
        now = cls._utcnow()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(CaseSnapshot).where(CaseSnapshot.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is not None:
                if condensed_context is not None:
                    row.condensed_context = condensed_context
                if last_human_email_body is not None:
                    row.last_human_email_body = last_human_email_body
                row.updated_at = now
            else:
                session.add(CaseSnapshot(
                    case_id=case_id,
                    condensed_context=condensed_context,
                    last_human_email_body=last_human_email_body,
                ))
            await session.commit()

    @classmethod
    async def get_case_snapshot(cls, case_id: str) -> Optional[dict]:
        await cls.initialize()
        async with cls._session_maker() as session:
            row = (
                await session.execute(
                    select(CaseSnapshot).where(CaseSnapshot.case_id == case_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return {
                "case_id": row.case_id,
                "condensed_context": row.condensed_context,
                "last_human_email_body": row.last_human_email_body,
                "updated_at": row.updated_at,
            }

    @classmethod
    async def get_active_pm_workspaces(cls) -> list[str]:
        """Return distinct workspace slugs with active PM sessions."""
        await cls.initialize()
        async with cls._session_maker() as session:
            rows = (
                await session.execute(
                    select(PmSession.workspace_slug)
                    .where(PmSession.status == "active")
                    .distinct()
                )
            ).scalars().all()
            return list(rows)
