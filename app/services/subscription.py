"""Mandatory subscription-gate business logic."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.subscription import subscription_keyboard
from app.models.errors import ActivationRequiredError, ModerationError
from app.repositories.activations import ActivationRepository
from app.services.messages import TEXTS, ModerationTexts
from app.utils.locks import KeyedLockRegistry
from app.utils.telegram import is_chat_administrator, is_subscription_member
from app.utils.time import utc_now

logger = logging.getLogger(__name__)
_activation_locks = KeyedLockRegistry()
SUBSCRIPTION_CACHE_TTL = timedelta(minutes=10)


class SubscriptionVerificationCache:
    def __init__(self) -> None:
        self._entries: dict[int, datetime] = {}
        self._lock = asyncio.Lock()

    async def contains(self, user_id: int) -> bool:
        now = utc_now()
        async with self._lock:
            expires_at = self._entries.get(user_id)
            if expires_at is None or expires_at <= now:
                self._entries.pop(user_id, None)
                return False
            return True

    async def add(self, user_id: int) -> None:
        async with self._lock:
            self._entries[user_id] = utc_now() + SUBSCRIPTION_CACHE_TTL

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    async def discard(self, user_id: int) -> None:
        async with self._lock:
            self._entries.pop(user_id, None)


_verification_cache = SubscriptionVerificationCache()


class SubscriptionGateService:
    def __init__(
        self,
        *,
        bot: Bot,
        session: AsyncSession,
        settings: Settings,
        texts: ModerationTexts = TEXTS,
        verification_cache: SubscriptionVerificationCache = _verification_cache,
    ) -> None:
        self._bot = bot
        self._session = session
        self._settings = settings
        self._texts = texts
        self._repository = ActivationRepository(session)
        self._verification_cache = verification_cache

    async def ensure_active(self, chat_id: int) -> None:
        if not await self._repository.is_active(chat_id):
            await self.send_prompt_if_needed(chat_id)
            raise ActivationRequiredError(self._texts.activation_required)

    async def send_prompt_if_needed(self, chat_id: int) -> Message | None:
        async with _activation_locks.lock(chat_id):
            activation = await self._repository.get(chat_id)
            if activation is not None and activation.is_active:
                return None
            prompt_text = self._texts.subscription_prompt
            if activation is not None and activation.activation_message_id is not None:
                try:
                    await self._bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=activation.activation_message_id,
                        text=prompt_text,
                        reply_markup=self._subscription_keyboard(chat_id),
                        disable_web_page_preview=True,
                    )
                    return None
                except TelegramAPIError:
                    logger.info(
                        "activation_message_recreate_required",
                        extra={
                            "chat_id": chat_id,
                            "message_id": activation.activation_message_id,
                        },
                        exc_info=True,
                    )
            try:
                message = await self._bot.send_message(
                    chat_id=chat_id,
                    text=prompt_text,
                    reply_markup=self._subscription_keyboard(chat_id),
                    disable_web_page_preview=True,
                )
            except TelegramAPIError:
                logger.exception(
                    "activation_message_send_failed", extra={"chat_id": chat_id}
                )
                return None
            await self._repository.set_pending_message(
                chat_id=chat_id, message_id=message.message_id
            )
            await self._session.commit()
            return message

    async def verify_and_activate(
        self, *, chat_id: int, user_id: int, admin_name: str
    ) -> None:
        async with _activation_locks.lock(chat_id):
            if not await self._is_group_administrator(chat_id, user_id):
                raise ModerationError(self._texts.subscription_admin_only)
            if not await self._verification_cache.contains(user_id):
                if not await self._has_required_subscriptions(user_id):
                    raise ModerationError(self._texts.subscription_required)
                await self._verification_cache.add(user_id)
            await self._repository.activate(
                chat_id=chat_id,
                verified_at=utc_now(),
                admin_id=user_id,
                admin_name=admin_name,
            )
            await self._session.commit()

    async def recheck_active_groups(self) -> int:
        activations = await self._repository.list_active_for_recheck()
        deactivated: list[int] = []
        for activation in activations:
            admin_id = activation.activating_admin_id
            if admin_id is None:
                continue
            async with _activation_locks.lock(activation.chat_id):
                current = await self._repository.get(activation.chat_id)
                if (
                    current is None
                    or not current.is_active
                    or current.activating_admin_id is None
                ):
                    continue
                try:
                    subscribed = await self._has_required_subscriptions(
                        current.activating_admin_id
                    )
                except ModerationError:
                    subscribed = False
                if subscribed:
                    await self._repository.touch_verification(
                        chat_id=current.chat_id, verified_at=utc_now()
                    )
                    await self._session.commit()
                    continue
                await self._repository.mark_inactive(chat_id=current.chat_id)
                await self._session.commit()
                await self._verification_cache.discard(current.activating_admin_id)
                deactivated.append(current.chat_id)
        for chat_id in deactivated:
            await self.send_prompt_if_needed(chat_id)
        return len(deactivated)

    async def clear_activation_message(self, *, chat_id: int, message_id: int) -> None:
        await self._repository.clear_activation_message(
            chat_id=chat_id, message_id=message_id
        )
        await self._session.commit()

    async def _is_group_administrator(self, chat_id: int, user_id: int) -> bool:
        try:
            return await is_chat_administrator(self._bot, chat_id, user_id)
        except TelegramAPIError as exc:
            logger.warning(
                "subscription_activation_admin_check_failed",
                extra={"chat_id": chat_id, "user_id": user_id, "error": str(exc)},
            )
            raise ModerationError(self._texts.subscription_check_failed) from exc

    async def _has_required_subscriptions(self, user_id: int) -> bool:
        try:
            for required_chat_id in (
                self._settings.required_chat_id,
                self._settings.required_channel_id,
            ):
                member = await self._bot.get_chat_member(required_chat_id, user_id)
                if not is_subscription_member(member):
                    return False
        except TelegramAPIError as exc:
            logger.warning(
                "subscription_membership_check_failed",
                extra={"user_id": user_id, "error": str(exc)},
            )
            raise ModerationError(self._texts.subscription_check_failed) from exc
        return True

    def _subscription_keyboard(self, chat_id: int) -> InlineKeyboardMarkup:
        return subscription_keyboard(
            chat_id=chat_id,
            chat_url=self._settings.required_chat_url,
            channel_url=self._settings.required_channel_url,
        )
