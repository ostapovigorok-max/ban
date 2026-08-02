"""Application lifecycle wiring for aiogram polling."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config.logging import configure_logging
from app.config.settings import Settings
from app.database.session import (
    create_session_factory,
    create_sqlalchemy_engine,
    log_database_diagnostics,
)
from app.handlers import callbacks, moderation, subscription
from app.scheduler.punishment_scheduler import PunishmentScheduler
from app.services.startup import (
    log_startup_diagnostics,
    register_group_commands,
    warn_known_groups_about_missing_permissions,
)

logger = logging.getLogger(__name__)


async def run_bot(settings: Settings) -> None:
    """Run the bot until polling is stopped or the process receives a signal."""

    configure_logging(settings.log_level)
    engine = create_sqlalchemy_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    scheduler = PunishmentScheduler(
        bot=bot,
        session_factory=session_factory,
        settings=settings,
    )

    dispatcher.include_router(subscription.router)
    dispatcher.include_router(moderation.router)
    dispatcher.include_router(callbacks.router)
    dispatcher["settings"] = settings
    dispatcher["session_factory"] = session_factory
    dispatcher["punishment_scheduler"] = scheduler

    try:
        await log_database_diagnostics(engine, settings.database_url)
        await register_group_commands(bot, settings)
        await log_startup_diagnostics(bot=bot, engine=engine, settings=settings)
        await warn_known_groups_about_missing_permissions(
            bot=bot,
            session_factory=session_factory,
        )
        await scheduler.start()
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await scheduler.stop()
        await bot.session.close()
        await engine.dispose()
        logging.shutdown()
