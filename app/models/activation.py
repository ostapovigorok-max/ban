"""Persistent group activation model for the subscription gate."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime


class GroupActivation(Base):
    __tablename__ = "group_activations"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    activation_time: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    activation_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activating_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, index=True
    )
    activating_admin_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    permission_warning_sent_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
