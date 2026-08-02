"""Business operations for applying and releasing restrictions."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.restriction import release_restriction_keyboard
from app.models.errors import ModerationError
from app.models.punishment import Punishment, PunishmentStatus
from app.repositories.punishments import PunishmentRepository
from app.services.messages import TEXTS, ModerationTexts
from app.services.types import CallbackResult, CallbackResultKind, ModerationRequest
from app.utils.html import user_mention
from app.utils.locks import KeyedLockRegistry
from app.utils.telegram import (
    has_moderation_permissions,
    is_chat_administrator,
    is_chat_member_restricted,
    muted_permissions,
    unrestricted_permissions,
)
from app.utils.time import as_utc, utc_now

logger = logging.getLogger(__name__)
_punishment_locks = KeyedLockRegistry()


class ModerationService:
    def __init__(
        self,
        *,
        bot: Bot,
        session: AsyncSession,
        settings: Settings,
        texts: ModerationTexts = TEXTS,
    ) -> None:
        self._bot = bot
        self._session = session
        self._repository = PunishmentRepository(session)
        self._settings = settings
        self._texts = texts

    async def apply_restriction(
        self,
        request: ModerationRequest,
        *,
        require_moderator: bool = True,
        delete_command_message: bool = True,
    ) -> Punishment:
        if require_moderator:
            await self._ensure_moderator(request.chat_id, request.admin_id)
        await self._ensure_bot_permissions(request.chat_id)
        await self._ensure_target_is_not_administrator(
            request.chat_id, request.target_user_id
        )
        if await self.reconcile_active_punishment(
            request.chat_id, request.target_user_id
        ):
            raise ModerationError(self._texts.user_already_restricted)
        logger.info(
            "creating_new_punishment",
            extra={
                "chat_id": request.chat_id,
                "target_user_id": request.target_user_id,
                "admin_id": request.admin_id,
            },
        )
        expires_at = utc_now() + timedelta(days=self._settings.restriction_days)
        try:
            await self._bot.delete_message(
                chat_id=request.chat_id, message_id=request.offending_message_id
            )
            if delete_command_message:
                await self._bot.delete_message(
                    chat_id=request.chat_id, message_id=request.command_message_id
                )
            await self._bot.restrict_chat_member(
                chat_id=request.chat_id,
                user_id=request.target_user_id,
                permissions=muted_permissions(),
                until_date=expires_at,
                use_independent_chat_permissions=True,
            )
        except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError) as exc:
            logger.warning(
                "apply_restriction_telegram_error",
                extra={
                    "chat_id": request.chat_id,
                    "target_user_id": request.target_user_id,
                    "error": str(exc),
                },
            )
            raise ModerationError(self._texts.moderation_failed) from exc
        try:
            punishment = await self._repository.create(
                chat_id=request.chat_id,
                user_id=request.target_user_id,
                admin_id=request.admin_id,
                admin_username=request.admin_username,
                admin_display_name=request.admin_display_name,
                user_display_name=request.target_display_name,
                expires_at=expires_at,
            )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ModerationError(self._texts.user_already_restricted) from exc
        notification = await self._send_punishment_notification(
            request=request, punishment=punishment
        )
        if notification is not None:
            await self._repository.set_notification_message_id(
                punishment, notification.message_id
            )
            await self._session.commit()
        logger.info(
            "restriction_applied",
            extra={
                "punishment_id": punishment.id,
                "chat_id": request.chat_id,
                "target_user_id": request.target_user_id,
                "admin_id": request.admin_id,
                "expires_at": expires_at.isoformat(),
            },
        )
        return punishment

    async def is_administrator(self, chat_id: int, user_id: int) -> bool:
        return await self._is_administrator(chat_id, user_id)

    async def validate_community_vote_target(
        self, *, chat_id: int, target_user_id: int
    ) -> None:
        await self._ensure_bot_permissions(chat_id)
        await self._ensure_target_is_not_administrator(chat_id, target_user_id)
        if await self.reconcile_active_punishment(chat_id, target_user_id):
            raise ModerationError(self._texts.user_already_restricted)

    async def handle_release_click(
        self, *, punishment_id: int, chat_id: int, clicker_id: int
    ) -> CallbackResult:
        async with _punishment_locks.lock(punishment_id):
            return await self._handle_release_click_locked(
                punishment_id=punishment_id, chat_id=chat_id, clicker_id=clicker_id
            )

    async def _handle_release_click_locked(
        self, *, punishment_id: int, chat_id: int, clicker_id: int
    ) -> CallbackResult:
        punishment = await self._repository.get_by_id(punishment_id)
        if (
            punishment is None
            or punishment.chat_id != chat_id
            or punishment.status != PunishmentStatus.ACTIVE
        ):
            return CallbackResult(
                kind=CallbackResultKind.ALERT, text=self._texts.action_unavailable
            )
        if as_utc(punishment.expires_at) <= utc_now():
            await self.expire_punishment(punishment)
            return CallbackResult(
                kind=CallbackResultKind.ALERT, text=self._texts.action_unavailable
            )
        if clicker_id == punishment.user_id:
            return CallbackResult(
                kind=CallbackResultKind.ALERT, text=self._texts.action_unavailable
            )
        if clicker_id != punishment.admin_id:
            return CallbackResult(
                kind=CallbackResultKind.ALERT, text=self._texts.callback_admin_only
            )
        if not await self._is_administrator(chat_id, clicker_id):
            return CallbackResult(
                kind=CallbackResultKind.ALERT, text=self._texts.callback_admin_only
            )
        released = await self._release_punishment(punishment, PunishmentStatus.RELEASED)
        return CallbackResult(
            kind=CallbackResultKind.ANSWER if released else CallbackResultKind.ALERT,
            text=None if released else self._texts.action_unavailable,
        )

    async def expire_punishment_by_id(self, punishment_id: int) -> bool:
        async with _punishment_locks.lock(punishment_id):
            punishment = await self._repository.get_by_id(punishment_id)
            if (
                punishment is None
                or punishment.status != PunishmentStatus.ACTIVE
                or as_utc(punishment.expires_at) > utc_now()
            ):
                return False
            return await self.expire_punishment(punishment)

    async def expire_due_punishments(self) -> int:
        count = 0
        for punishment in await self._repository.list_due(utc_now()):
            if await self.expire_punishment_by_id(punishment.id):
                count += 1
        return count

    async def expire_punishment(self, punishment: Punishment) -> bool:
        return await self._release_punishment(punishment, PunishmentStatus.EXPIRED)

    async def reconcile_active_punishment(self, chat_id: int, user_id: int) -> bool:
        existing = await self._repository.get_active_for_user(
            chat_id=chat_id, user_id=user_id
        )
        if existing is None:
            return False
        if as_utc(existing.expires_at) <= utc_now():
            await self.expire_punishment_by_id(existing.id)
            return False
        try:
            member = await self._bot.get_chat_member(chat_id, user_id)
        except TelegramAPIError as exc:
            logger.warning(
                "active_punishment_verification_failed",
                extra={
                    "punishment_id": existing.id,
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return True
        logger.info(
            "telegram_member_status",
            extra={
                "status": getattr(member, "status", None),
                "punishment_id": existing.id,
                "user_id": user_id,
            },
        )
        if is_chat_member_restricted(member):
            return True
        logger.info(
            "stale_active_punishment_detected",
            extra={
                "punishment_id": existing.id,
                "chat_id": chat_id,
                "user_id": user_id,
            },
        )
        await self._repository.mark_status(existing, PunishmentStatus.EXPIRED)
        await self._session.commit()
        logger.info(
            "stale_active_punishment_resolved",
            extra={
                "punishment_id": existing.id,
                "chat_id": chat_id,
                "user_id": user_id,
            },
        )
        return False

    async def _ensure_moderator(self, chat_id: int, admin_id: int) -> None:
        if not await self._is_administrator(chat_id, admin_id):
            raise ModerationError(self._texts.admin_required)

    async def _ensure_bot_permissions(self, chat_id: int) -> None:
        try:
            ok = await has_moderation_permissions(self._bot, chat_id)
        except TelegramAPIError as exc:
            raise ModerationError(self._texts.bot_permissions_required) from exc
        if not ok:
            raise ModerationError(self._texts.bot_permissions_required)

    async def _ensure_target_is_not_administrator(
        self, chat_id: int, user_id: int
    ) -> None:
        if await self._is_administrator(chat_id, user_id):
            raise ModerationError(self._texts.target_is_administrator)

    async def _ensure_no_active_punishment(self, chat_id: int, user_id: int) -> None:
        if await self.reconcile_active_punishment(chat_id, user_id):
            raise ModerationError(self._texts.user_already_restricted)

    async def _is_administrator(self, chat_id: int, user_id: int) -> bool:
        try:
            return await is_chat_administrator(self._bot, chat_id, user_id)
        except TelegramAPIError as exc:
            raise ModerationError(self._texts.member_status_unavailable) from exc

    async def _send_punishment_notification(
        self, *, request: ModerationRequest, punishment: Punishment
    ) -> Message | None:
        text = self._texts.punishment_notification.format(
            mention=user_mention(
                user_id=request.target_user_id, display_name=request.target_display_name
            ),
            days=self._settings.restriction_days,
        )
        try:
            return await self._bot.send_message(
                chat_id=request.chat_id,
                text=text,
                reply_markup=release_restriction_keyboard(
                    punishment.id, rules_url=self._settings.rules_url
                ),
            )
        except TelegramAPIError:
            logger.warning(
                "punishment_notification_failed",
                extra={"punishment_id": punishment.id, "chat_id": request.chat_id},
                exc_info=True,
            )
            return None

    async def _release_punishment(
        self, punishment: Punishment, status: PunishmentStatus
    ) -> bool:
        await self._remove_telegram_restriction(punishment)
        transitioned = await self._repository.mark_status_if_active(
            punishment.id, status
        )
        if not transitioned:
            await self._session.rollback()
            return False
        await self._session.commit()
        await self._disable_notification_button(punishment)
        await self._send_release_notification(punishment)
        return True

    async def _remove_telegram_restriction(self, punishment: Punishment) -> None:
        await self._bot.restrict_chat_member(
            chat_id=punishment.chat_id,
            user_id=punishment.user_id,
            permissions=unrestricted_permissions(),
            use_independent_chat_permissions=True,
        )

    async def _disable_notification_button(self, punishment: Punishment) -> None:
        if punishment.notification_message_id is not None:
            try:
                await self._bot.edit_message_reply_markup(
                    chat_id=punishment.chat_id,
                    message_id=punishment.notification_message_id,
                    reply_markup=None,
                )
            except TelegramAPIError:
                logger.info(
                    "notification_button_disable_failed",
                    extra={"punishment_id": punishment.id},
                    exc_info=True,
                )

    async def _send_release_notification(self, punishment: Punishment) -> None:
        text = self._texts.released_notification.format(
            mention=user_mention(
                user_id=punishment.user_id, display_name=punishment.user_display_name
            )
        )
        try:
            await self._bot.send_message(chat_id=punishment.chat_id, text=text)
        except TelegramAPIError:
            logger.warning(
                "release_notification_failed",
                extra={"punishment_id": punishment.id},
                exc_info=True,
            )
