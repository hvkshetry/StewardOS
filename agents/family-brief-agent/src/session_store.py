"""Async SQLite session store for conversation continuity and Gmail watch state."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Column, DateTime, String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from src.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()


class EmailSession(Base):
    """Tracks Codex conversation IDs per Gmail thread for session continuity."""

    __tablename__ = "email_sessions"

    id = Column(String, primary_key=True)  # thread_id
    thread_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GmailWatchState(Base):
    """Tracks Gmail watch() state per email address for incremental history sync."""

    __tablename__ = "gmail_watch_state"

    email = Column(String, primary_key=True)
    history_id = Column(BigInteger, nullable=False)
    expiration = Column(BigInteger, nullable=True)  # Unix ms timestamp
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SessionStore:
    """Manage email sessions and Gmail watch state."""

    _engine = None
    _session_maker = None

    @classmethod
    async def initialize(cls):
        """Initialize database connection and create tables."""
        if cls._engine is None:
            cls._engine = create_async_engine(
                settings.database_url,
                echo=False,
            )
            cls._session_maker = async_sessionmaker(
                cls._engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            async with cls._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            logger.info("Session store initialized")

    @classmethod
    async def get_session(cls, thread_id: str) -> Optional[str]:
        """Get existing Codex conversation_id for a Gmail thread.

        Returns the conversation_id if a session exists, None otherwise.
        """
        await cls.initialize()

        async with cls._session_maker() as session:
            stmt = select(EmailSession).where(EmailSession.thread_id == thread_id)
            result = await session.execute(stmt)
            email_session = result.scalar_one_or_none()

            if email_session:
                return email_session.conversation_id

        return None

    @classmethod
    async def store_session(
        cls,
        thread_id: str,
        conversation_id: str,
    ):
        """Store or update a conversation session for a Gmail thread."""
        await cls.initialize()

        async with cls._session_maker() as session:
            stmt = select(EmailSession).where(EmailSession.thread_id == thread_id)
            result = await session.execute(stmt)
            email_session = result.scalar_one_or_none()

            if email_session:
                email_session.conversation_id = conversation_id
                email_session.updated_at = datetime.utcnow()
            else:
                email_session = EmailSession(
                    id=thread_id,
                    thread_id=thread_id,
                    conversation_id=conversation_id,
                )
                session.add(email_session)

            await session.commit()

    @classmethod
    async def get_watch_state(cls, email: str) -> Optional[dict]:
        """Get Gmail watch state for an email address.

        Returns dict with history_id and expiration, or None if not tracked.
        """
        await cls.initialize()

        async with cls._session_maker() as session:
            stmt = select(GmailWatchState).where(GmailWatchState.email == email)
            result = await session.execute(stmt)
            state = result.scalar_one_or_none()

            if state:
                return {
                    "history_id": state.history_id,
                    "expiration": state.expiration,
                    "updated_at": state.updated_at,
                }

        return None

    @classmethod
    async def update_watch_state(
        cls,
        email: str,
        history_id: int,
        expiration: Optional[int] = None,
    ):
        """Update Gmail watch state for an email address.

        Args:
            email: The Gmail address being watched.
            history_id: The latest history_id from Gmail.
            expiration: Unix ms timestamp when the watch expires (from users.watch).
        """
        await cls.initialize()

        async with cls._session_maker() as session:
            stmt = select(GmailWatchState).where(GmailWatchState.email == email)
            result = await session.execute(stmt)
            state = result.scalar_one_or_none()

            if state:
                state.history_id = history_id
                if expiration is not None:
                    state.expiration = expiration
                state.updated_at = datetime.utcnow()
            else:
                state = GmailWatchState(
                    email=email,
                    history_id=history_id,
                    expiration=expiration,
                )
                session.add(state)

            await session.commit()
