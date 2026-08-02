"""Startup-time Telegram setup and self-checks."""

from __future__ import annotations

import logging
import platform
from importlib.metadata import version

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config.settings import Settings, sqlite_database_path
from app.repositories.activations import ActivationRepository
from app.services.messages import TEXTS, ModerationTexts
from app.utils.telegram import bot_can_moderate
from app.utils.time import utc_now

logger = logging.getLogger(__name__)
BOT_VERSION = "1.0.0"


async def register_group_commands(bot: Bot, settings: Settings) -> None:
    try:
        await bot.set_my_commands(
            [
                BotCommand(
                    command=settings.moderation_command.removeprefix("/"),
                    description="Обмежити користувача на 7 діб",
                )
            ],
            scope=BotCommandScopeAllGroupChats(),
        )
    except TelegramAPIError:
        logger.warning("group_command_registration_failed", exc_info=True)


async def log_startup_diagnostics(
    *, bot: Bot, engine: AsyncEngine, settings: Settings
) -> None:
    bot_identity = await bot.get_me()
    logger.info(
        "startup_diagnostics",
        extra={
            "bot_id": bot_identity.id,
            "bot_username": bot_identity.username,
            "bot_version": BOT_VERSION,
            "database_path": str(sqlite_database_path(settings.database_url)),
            "database_schema_revision": await _database_schema_revision(engine),
            "python_version": platform.python_version(),
            "aiogram_version": version("aiogram"),
            "required_chat_id": settings.required_chat_id,
            "required_channel_id": settings.required_channel_id,
            "subscription_gate_enabled": "yes",
        },
    )


async def warn_known_groups_about_missing_permissions(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    texts: ModerationTexts = TEXTS,
) -> int:
    bot_identity = await bot.get_me()
    warnings = 0
    async with session_factory() as session:
        repo = ActivationRepository(session)
        for activation in await repo.list_known_groups():
            try:
                member = await bot.get_chat_member(activation.chat_id, bot_identity.id)
            except TelegramAPIError:
                continue
            if bot_can_moderate(member):
                await repo.clear_permission_warning(chat_id=activation.chat_id)
                continue
            if activation.permission_warning_sent_at is not None:
                continue
            try:
                await bot.send_message(
                    chat_id=activation.chat_id, text=texts.bot_permission_warning
                )
            except TelegramAPIError:
                continue
            await repo.mark_permission_warning_sent(
                chat_id=activation.chat_id, sent_at=utc_now()
            )
            warnings += 1
        await session.commit()
    return warnings


async def _database_schema_revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as connection:
        try:
            return (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one_or_none()
        except SQLAlchemyError:
            return None
