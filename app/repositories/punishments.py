"""Repository for punishments."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.punishment import Punishment, PunishmentStatus


class PunishmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        chat_id: int,
        user_id: int,
        admin_id: int,
        admin_username: str | None,
        admin_display_name: str,
        user_display_name: str,
        expires_at: datetime,
    ) -> Punishment:
        punishment = Punishment(
            chat_id=chat_id,
            user_id=user_id,
            admin_id=admin_id,
            admin_username=admin_username,
            admin_display_name=admin_display_name,
            user_display_name=user_display_name,
            expires_at=expires_at,
        )
        self._session.add(punishment)
        await self._session.flush()
        return punishment

    async def get_by_id(self, punishment_id: int) -> Punishment | None:
        return await self._session.get(Punishment, punishment_id)

    async def get_active_for_user(
        self, *, chat_id: int, user_id: int
    ) -> Punishment | None:
        statement = select(Punishment).where(
            Punishment.chat_id == chat_id,
            Punishment.user_id == user_id,
            Punishment.status == PunishmentStatus.ACTIVE,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def list_due(self, now: datetime) -> list[Punishment]:
        statement = select(Punishment).where(
            Punishment.status == PunishmentStatus.ACTIVE, Punishment.expires_at <= now
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def list_future(self, now: datetime) -> list[Punishment]:
        statement = select(Punishment).where(
            Punishment.status == PunishmentStatus.ACTIVE, Punishment.expires_at > now
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def mark_status_if_active(
        self, punishment_id: int, status: PunishmentStatus
    ) -> bool:
        statement = (
            update(Punishment)
            .where(
                Punishment.id == punishment_id,
                Punishment.status == PunishmentStatus.ACTIVE,
            )
            .values(status=status)
        )
        result = cast(Any, await self._session.execute(statement))
        rowcount = int(result.rowcount)
        return rowcount == 1

    async def set_notification_message_id(
        self, punishment: Punishment, message_id: int
    ) -> None:
        punishment.notification_message_id = message_id
        await self._session.flush()
