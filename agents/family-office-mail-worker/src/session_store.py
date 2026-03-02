"""Async SQLite state store for thread sessions, idempotency, and Gmail watch cursor."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


class EmailSession(Base):
    """Persists Codex thread sessions keyed by alias+thread."""

    __tablename__ = "email_sessions"

    id = Column(String, primary_key=True)
    session_key = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GmailWatchState(Base):
    """Tracks last history cursor for incremental Gmail sync."""

    __tablename__ = "gmail_watch_state"

    email = Column(String, primary_key=True)
    history_id = Column(BigInteger, nullable=False)
    expiration = Column(BigInteger, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SessionStore:
    """Storage helper for thread continuity, idempotency, and watch state."""

    _engine = None
    _session_maker = None

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
    async def get_session(cls, session_key: str) -> Optional[str]:
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(EmailSession).where(EmailSession.session_key == session_key)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row and datetime.utcnow() - row.updated_at < timedelta(days=30):
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
                row.updated_at = datetime.utcnow()
            else:
                row = EmailSession(
                    id=session_key,
                    session_key=session_key,
                    conversation_id=conversation_id,
                )
                session.add(row)

            await session.commit()

    @classmethod
    async def is_message_replied(cls, message_id: str) -> bool:
        await cls.initialize()
        async with cls._session_maker() as session:
            stmt = select(ProcessedGmailMessage).where(ProcessedGmailMessage.message_id == message_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return bool(row and row.status == "sent")

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
                row.updated_at = datetime.utcnow()
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
                row.updated_at = datetime.utcnow()
            else:
                row = GmailWatchState(
                    email=email,
                    history_id=history_id,
                    expiration=expiration,
                )
                session.add(row)

            await session.commit()
