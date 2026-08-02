"""Reply-based moderation command handler."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.models.errors import ActivationRequiredError, ModerationError
from app.scheduler.punishment_scheduler import PunishmentScheduler
from app.services.community_vote import CommunityVoteService
from app.services.messages import TEXTS
from app.services.moderation import ModerationService
from app.services.rate_limit import admin_moderation_limiter, community_vote_limiter
from app.services.subscription import SubscriptionGateService
from app.services.types import ModerationRequest

router = Router(name=__name__)
logger = logging.getLogger(__name__)


@router.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text)
async def moderate_reply(
    message: Message,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    punishment_scheduler: PunishmentScheduler,
) -> None:
    if message.text is None:
        return
    bot_identity = await bot.get_me()
    if not _is_moderation_command(
        message.text, settings.moderation_command, bot_identity.username
    ):
        return
    if message.reply_to_message is None:
        await message.answer(TEXTS.reply_required)
        return
    if message.from_user is None:
        await message.answer(TEXTS.admin_required)
        return
    if message.reply_to_message.from_user is None:
        await message.answer(TEXTS.unsupported_sender)
        return
    request = ModerationRequest(
        chat_id=message.chat.id,
        command_message_id=message.message_id,
        offending_message_id=message.reply_to_message.message_id,
        admin_id=message.from_user.id,
        admin_username=message.from_user.username,
        admin_display_name=message.from_user.full_name,
        target_user_id=message.reply_to_message.from_user.id,
        target_display_name=message.reply_to_message.from_user.full_name,
    )
    async with session_factory() as session:
        activation = SubscriptionGateService(
            bot=bot, session=session, settings=settings
        )
        moderation = ModerationService(bot=bot, session=session, settings=settings)
        votes = CommunityVoteService(bot=bot, session=session, settings=settings)
        try:
            await activation.ensure_active(request.chat_id)
            if await moderation.is_administrator(request.chat_id, request.admin_id):
                if not await admin_moderation_limiter.allow(
                    (request.chat_id, request.admin_id)
                ):
                    raise ModerationError(TEXTS.admin_rate_limited)
                punishment = await moderation.apply_restriction(request)
                punishment_scheduler.schedule(punishment.id, punishment.expires_at)
            else:
                if not await community_vote_limiter.allow(request.chat_id):
                    raise ModerationError(TEXTS.community_vote_rate_limited)
                vote_session = await votes.start_vote(request)
                punishment_scheduler.schedule_vote(
                    vote_session.id, vote_session.expires_at
                )
        except ActivationRequiredError:
            return
        except ModerationError as exc:
            await _send_error(bot, message.chat.id, exc.user_message)
        except Exception:
            logger.exception(
                "unexpected_moderation_error", extra={"chat_id": request.chat_id}
            )
            await _send_error(bot, message.chat.id, TEXTS.moderation_failed)


def _is_moderation_command(text: str, command: str, bot_username: str | None) -> bool:
    token = text.split(maxsplit=1)[0].lower()
    return token == command or (
        bot_username is not None and token == f"{command}@{bot_username.lower()}"
    )


async def _send_error(bot: Bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        logger.exception("moderation_error_message_failed", extra={"chat_id": chat_id})
