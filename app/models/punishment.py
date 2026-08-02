"""Persistent punishment model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Enum, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from app.database.base import Base
from app.database.types import UTCDateTime
from app.utils.time import utc_now


class PunishmentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class Punishment(Base):
    __tablename__ = "punishments"
    __table_args__ = (
        Index("ix_punishments_chat_user_status", "chat_id", "user_id", "status"),
        Index("ix_punishments_status_expires_at", "status", "expires_at"),
        Index(
            "uq_punishments_active_chat_user",
            "chat_id",
            "user_id",
            unique=True,
            sqlite_where=expression.text("status = 'ACTIVE'"),
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    admin_username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    admin_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    user_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    notification_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[PunishmentStatus] = mapped_column(
        Enum(PunishmentStatus, native_enum=False, length=16),
        default=PunishmentStatus.ACTIVE,
        nullable=False,
        index=True,
    )
