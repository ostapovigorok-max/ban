"""Restriction and vote callback handlers."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.keyboards.community_vote import CommunityVoteCallback
from app.keyboards.restriction import RestrictionCallback
from app.models.errors import ActivationRequiredError, ModerationError
from app.services.community_vote import CommunityVoteService
from app.services.messages import TEXTS
from app.services.moderation import ModerationService
from app.services.subscription import SubscriptionGateService
from app.services.types import CallbackResultKind

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
    elif result.kind == CallbackResultKind.URL:
        await callback.answer(url=result.url)
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
