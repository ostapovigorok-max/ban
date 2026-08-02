"""Restriction and vote callback handlers."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery
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
            await _answer_release_contact(
                callback=callback,
                punishment_id=punishment.id,
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
    elif result.kind == CallbackResultKind.URL:
        await _answer_release_url(
            callback=callback,
            bot=bot,
            punishment_id=callback_data.punishment_id,
            url=result.url,
        )
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


async def _answer_release_contact(
    *,
    callback: CallbackQuery,
    punishment_id: int,
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
        await callback.answer(url=f"https://t.me/{admin_username}")
        return
    await callback.answer(TEXTS.admin_contact_unavailable, show_alert=True)


async def _answer_release_url(
    *,
    callback: CallbackQuery,
    bot: Bot,
    punishment_id: int,
    url: str | None,
) -> None:
    """Answer only with Bot API-supported callback redirect URLs."""

    logger.info(
        "release_callback_url_requested",
        extra={"punishment_id": punishment_id, "result_url": url},
    )
    try:
        bot_username = (await bot.get_me()).username
    except TelegramAPIError:
        logger.warning(
            "release_callback_url_bot_identity_unavailable",
            extra={"punishment_id": punishment_id, "result_url": url},
            exc_info=True,
        )
        await callback.answer()
        return

    if not _is_bot_start_url(url=url, bot_username=bot_username):
        logger.warning(
            "release_callback_url_rejected",
            extra={
                "punishment_id": punishment_id,
                "result_url": url,
                "bot_username": bot_username,
            },
        )
        await callback.answer()
        return

    try:
        await callback.answer(url=url)
    except TelegramBadRequest:
        logger.warning(
            "release_callback_url_telegram_rejected",
            extra={"punishment_id": punishment_id, "result_url": url},
            exc_info=True,
        )
        await callback.answer()


def _is_bot_start_url(*, url: str | None, bot_username: str | None) -> bool:
    """Return whether *url* is a supported deep link for this bot."""

    if not url or not bot_username:
        return False

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.casefold() != "t.me":
        return False
    if parsed.path.strip("/").casefold() != bot_username.casefold():
        return False

    start_values = parse_qs(parsed.query).get("start", [])
    return any(start_values)
