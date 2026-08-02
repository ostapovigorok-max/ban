"""Subscription-gate handlers for group activation."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, ChatMemberUpdated
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.keyboards.subscription import SubscriptionCallback
from app.models.errors import ModerationError
from app.repositories.activations import ActivationRepository
from app.scheduler.punishment_scheduler import PunishmentScheduler
from app.services.messages import TEXTS
from app.services.subscription import SubscriptionGateService

router = Router(name=__name__)
logger = logging.getLogger(__name__)


@router.my_chat_member(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def prompt_for_subscription(
    event: ChatMemberUpdated,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if event.old_chat_member.status not in {
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED,
    }:
        return
    if event.new_chat_member.status not in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
    }:
        return
    async with session_factory() as session:
        await SubscriptionGateService(
            bot=bot, session=session, settings=settings
        ).send_prompt_if_needed(event.chat.id)


@router.callback_query(
    F.message.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    SubscriptionCallback.filter(F.action == "verify"),
)
async def verify_subscription(
    callback: CallbackQuery,
    callback_data: SubscriptionCallback,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    punishment_scheduler: PunishmentScheduler,
) -> None:
    if callback.message is None or callback.message.chat.id != callback_data.chat_id:
        await callback.answer(TEXTS.action_unavailable, show_alert=True)
        return
    async with session_factory() as session:
        activation = await ActivationRepository(session).get(callback_data.chat_id)
        if activation is not None and activation.is_active:
            await callback.answer(TEXTS.action_unavailable, show_alert=True)
            return
        try:
            await SubscriptionGateService(
                bot=bot, session=session, settings=settings
            ).verify_and_activate(
                chat_id=callback_data.chat_id,
                user_id=callback.from_user.id,
                admin_name=callback.from_user.full_name,
            )
        except ModerationError as exc:
            await callback.answer(exc.user_message, show_alert=True)
            return
    try:
        await bot.edit_message_text(
            chat_id=callback_data.chat_id,
            message_id=callback.message.message_id,
            text=TEXTS.subscription_confirmed,
            reply_markup=None,
        )
    except TelegramAPIError:
        logger.info(
            "subscription_confirmation_message_unavailable",
            extra={"chat_id": callback_data.chat_id},
        )
    punishment_scheduler.schedule_activation_message_cleanup(
        chat_id=callback_data.chat_id, message_id=callback.message.message_id
    )
    await callback.answer()
