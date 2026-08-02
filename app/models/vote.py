"""Persistent community-voting models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from app.database.base import Base
from app.database.types import UTCDateTime
from app.utils.time import utc_now


class VoteSessionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class VoteSession(Base):
    __tablename__ = "vote_sessions"
    __table_args__ = (
        Index(
            "ix_vote_sessions_active_chat_offender",
            "chat_id",
            "offender_user_id",
            unique=True,
            sqlite_where=expression.text("status = 'ACTIVE'"),
        ),
        Index("ix_vote_sessions_status_expires_at", "status", "expires_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    callback_token: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    offender_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offender_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    offender_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    creator_username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    creator_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    voting_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    votes_required: Mapped[int] = mapped_column(Integer, nullable=False)
    votes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[VoteSessionStatus] = mapped_column(
        Enum(VoteSessionStatus, native_enum=False, length=16),
        default=VoteSessionStatus.ACTIVE,
        nullable=False,
        index=True,
    )


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("session_id", "voter_user_id", name="uq_votes_session_voter"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("vote_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voter_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
