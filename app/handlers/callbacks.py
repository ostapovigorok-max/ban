"""Restriction and vote callback handlers."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.keyboards.community_vote import CommunityVoteCallback
from app.keyboards.restriction import RestrictionCallback
from app.models.errors import ActivationRequiredError, ModerationError
from app.repositories.punishments import PunishmentRepository
from app.services.community_vote import CommunityVoteService
from app.services.messages import TEXTS
from app.services.moderation import ModerationService
from app.services.subscription import SubscriptionGateService
from app.services.types import CallbackResultKind

CONTACT_ADMIN_BUTTON_TEXT = "✉️ Написати адміністратору"

router = Router(name=__name__)
logger = logging.getLogger(__name__)


@router.callback_query(
    F.message.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    RestrictionCallback.filter(F.action == "release"),
)
async def release_restriction(
    callback: CallbackQuery,
    callback_data: RestrictionCallback,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if callback.message is None or callback.from_user is None:
        await callback.answer(TEXTS.action_unavailable, show_alert=True)
        return
    async with session_factory() as session:
        punishment = await PunishmentRepository(session).get_by_id(
            callback_data.punishment_id
        )
        if punishment is None or punishment.chat_id != callback.message.chat.id:
            await callback.answer(TEXTS.action_unavailable, show_alert=True)
            return
        if callback.from_user.id == punishment.user_id:
            await _show_release_contact_button(
                callback=callback,
                bot=bot,
                punishment_id=punishment.id,
                chat_id=punishment.chat_id,
                message_id=callback.message.message_id,
                admin_id=punishment.admin_id,
                admin_username=punishment.admin_username,
            )
            return
        try:
            await SubscriptionGateService(
                bot=bot, session=session, settings=settings
            ).ensure_active(callback.message.chat.id)
            result = await ModerationService(
                bot=bot, session=session, settings=settings
            ).handle_release_click(
                punishment_id=callback_data.punishment_id,
                chat_id=callback.message.chat.id,
                clicker_id=callback.from_user.id,
            )
        except (ActivationRequiredError, ModerationError) as exc:
            await callback.answer(exc.user_message, show_alert=True)
            return
        except (TelegramAPIError, Exception):
            logger.exception(
                "release_callback_error",
                extra={"punishment_id": callback_data.punishment_id},
            )
            await callback.answer(TEXTS.moderation_failed, show_alert=True)
            return
    if result.kind == CallbackResultKind.ALERT:
        await callback.answer(result.text, show_alert=True)
    else:
        await callback.answer()


@router.callback_query(CommunityVoteCallback.filter())
async def cast_community_vote(
    callback: CallbackQuery,
    callback_data: CommunityVoteCallback,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        try:
            result = await CommunityVoteService(
                bot=bot, session=session, settings=settings
            ).cast_vote(
                callback_token=callback_data.token, voter_user_id=callback.from_user.id
            )
        except (ModerationError, TelegramAPIError):
            await callback.answer(TEXTS.vote_failed, show_alert=True)
            return
    if result.alert is not None:
        await callback.answer(result.alert, show_alert=True)
    else:
        await callback.answer()


async def _show_release_contact_button(
    *,
    callback: CallbackQuery,
    bot: Bot,
    punishment_id: int,
    chat_id: int,
    message_id: int,
    admin_id: int,
    admin_username: str | None,
) -> None:
    logger.info(
        "release_callback_contact_requested",
        extra={
            "punishment_id": punishment_id,
            "admin_id": admin_id,
            "admin_username": admin_username,
        },
    )
    if admin_username:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=CONTACT_ADMIN_BUTTON_TEXT,
                            url=f"https://t.me/{admin_username}",
                        )
                    ]
                ]
            ),
        )
        await callback.answer()
        return
    await callback.answer(TEXTS.admin_contact_unavailable, show_alert=True)
