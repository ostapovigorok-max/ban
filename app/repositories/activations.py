"""Repository for persistent group activation state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activation import GroupActivation


class ActivationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, chat_id: int) -> GroupActivation | None:
        return await self._session.get(GroupActivation, chat_id)

    async def is_active(self, chat_id: int) -> bool:
        activation = await self.get(chat_id)
        return activation is not None and activation.is_active

    async def set_pending_message(
        self, *, chat_id: int, message_id: int
    ) -> GroupActivation:
        activation = await self.get(chat_id)
        if activation is None:
            activation = GroupActivation(
                chat_id=chat_id, is_active=False, activation_message_id=message_id
            )
            self._session.add(activation)
        elif not activation.is_active:
            activation.activation_message_id = message_id
        await self._session.flush()
        return activation

    async def activate(
        self, *, chat_id: int, verified_at: datetime, admin_id: int, admin_name: str
    ) -> GroupActivation:
        activation = await self.get(chat_id)
        if activation is None:
            activation = GroupActivation(chat_id=chat_id)
            self._session.add(activation)
        activation.is_active = True
        activation.activation_time = verified_at
        activation.last_verified_at = verified_at
        activation.activating_admin_id = admin_id
        activation.activating_admin_name = admin_name
        await self._session.flush()
        return activation

    async def touch_verification(self, *, chat_id: int, verified_at: datetime) -> None:
        activation = await self.get(chat_id)
        if activation is not None and activation.is_active:
            activation.last_verified_at = verified_at
            await self._session.flush()

    async def mark_inactive(self, *, chat_id: int) -> GroupActivation | None:
        activation = await self.get(chat_id)
        if activation is None:
            return None
        activation.is_active = False
        await self._session.flush()
        return activation

    async def clear_activation_message(self, *, chat_id: int, message_id: int) -> None:
        activation = await self.get(chat_id)
        if activation is not None and activation.activation_message_id == message_id:
            activation.activation_message_id = None
            await self._session.flush()

    async def list_active_with_activation_message(self) -> list[GroupActivation]:
        statement = select(GroupActivation).where(
            GroupActivation.is_active.is_(True),
            GroupActivation.activation_message_id.is_not(None),
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def list_active_for_recheck(self) -> list[GroupActivation]:
        statement = select(GroupActivation).where(
            GroupActivation.is_active.is_(True),
            GroupActivation.activating_admin_id.is_not(None),
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def list_known_groups(self) -> list[GroupActivation]:
        statement = select(GroupActivation).order_by(GroupActivation.chat_id)
        return list((await self._session.execute(statement)).scalars().all())

    async def mark_permission_warning_sent(
        self, *, chat_id: int, sent_at: datetime
    ) -> None:
        activation = await self.get(chat_id)
        if activation is None:
            activation = GroupActivation(chat_id=chat_id)
            self._session.add(activation)
        activation.permission_warning_sent_at = sent_at
        await self._session.flush()

    async def clear_permission_warning(self, *, chat_id: int) -> None:
        activation = await self.get(chat_id)
        if activation is not None:
            activation.permission_warning_sent_at = None
            await self._session.flush()
