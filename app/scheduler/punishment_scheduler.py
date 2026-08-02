"""Persistent expiry scheduler backed by active database rows."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.repositories.activations import ActivationRepository
from app.repositories.punishments import PunishmentRepository
from app.repositories.votes import VoteRepository
from app.services.cleanup import RuntimeCleanupService
from app.services.community_vote import CommunityVoteService
from app.services.moderation import ModerationService
from app.services.subscription import SubscriptionGateService
from app.utils.time import as_utc, utc_now

logger = logging.getLogger(__name__)


class PunishmentScheduler:
    def __init__(
        self,
        *,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._cleanup_service = RuntimeCleanupService(settings)

    async def start(self) -> None:
        self._scheduler.start()
        self._scheduler.add_job(
            self.reconcile,
            trigger=IntervalTrigger(minutes=5),
            id="punishment-expiry-reconciliation",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.reconcile_votes,
            trigger=IntervalTrigger(minutes=5),
            id="community-vote-reconciliation",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.run_cleanup,
            trigger=IntervalTrigger(hours=24),
            id="runtime-cleanup",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            self.recheck_subscriptions,
            trigger=IntervalTrigger(hours=24),
            id="subscription-activation-recheck",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        await self.run_cleanup()
        await self.reconcile()
        await self.reconcile_votes()
        await self.reconcile_activation_messages()
        await self.recheck_subscriptions()

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    def schedule(self, punishment_id: int, expires_at: datetime) -> None:
        run_at = max(as_utc(expires_at), utc_now())
        self._scheduler.add_job(
            self.expire,
            trigger=DateTrigger(run_date=run_at),
            args=[punishment_id],
            id=f"punishment-expiry:{punishment_id}",
            replace_existing=True,
            misfire_grace_time=None,
        )

    def schedule_vote(self, vote_session_id: int, expires_at: datetime) -> None:
        run_at = max(as_utc(expires_at), utc_now())
        self._scheduler.add_job(
            self.expire_vote,
            trigger=DateTrigger(run_date=run_at),
            args=[vote_session_id],
            id=f"community-vote-expiry:{vote_session_id}",
            replace_existing=True,
            misfire_grace_time=None,
        )

    def schedule_activation_message_cleanup(
        self, *, chat_id: int, message_id: int
    ) -> None:
        self._scheduler.add_job(
            self.delete_activation_message,
            trigger=DateTrigger(run_date=utc_now() + timedelta(seconds=3)),
            args=[chat_id, message_id],
            id=f"activation-message-cleanup:{chat_id}:{message_id}",
            replace_existing=True,
        )

    async def reconcile(self) -> None:
        async with self._session_factory() as session:
            repo = PunishmentRepository(session)
            service = ModerationService(
                bot=self._bot, session=session, settings=self._settings
            )
            await service.expire_due_punishments()
            active = await repo.list_future(utc_now())
        for punishment in active:
            self.schedule(punishment.id, punishment.expires_at)

    async def reconcile_votes(self) -> None:
        async with self._session_factory() as session:
            repo = VoteRepository(session)
            service = CommunityVoteService(
                bot=self._bot, session=session, settings=self._settings
            )
            await service.complete_ready_vote_sessions()
            await service.expire_due_vote_sessions()
            active = await repo.list_future(utc_now())
        for vote in active:
            self.schedule_vote(vote.id, vote.expires_at)

    async def run_cleanup(self) -> None:
        await self._cleanup_service.run()

    async def reconcile_activation_messages(self) -> None:
        async with self._session_factory() as session:
            activations = await ActivationRepository(
                session
            ).list_active_with_activation_message()
        for activation in activations:
            if activation.activation_message_id is not None:
                self.schedule_activation_message_cleanup(
                    chat_id=activation.chat_id,
                    message_id=activation.activation_message_id,
                )

    async def recheck_subscriptions(self) -> None:
        async with self._session_factory() as session:
            await SubscriptionGateService(
                bot=self._bot, session=session, settings=self._settings
            ).recheck_active_groups()

    async def expire(self, punishment_id: int) -> None:
        async with self._session_factory() as session:
            await ModerationService(
                bot=self._bot, session=session, settings=self._settings
            ).expire_punishment_by_id(punishment_id)

    async def expire_vote(self, vote_session_id: int) -> None:
        async with self._session_factory() as session:
            await CommunityVoteService(
                bot=self._bot, session=session, settings=self._settings
            ).expire_vote_session_by_id(vote_session_id)

    async def delete_activation_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            logger.info(
                "activation_message_cleanup_delete_failed",
                extra={"chat_id": chat_id, "message_id": message_id},
                exc_info=True,
            )
        async with self._session_factory() as session:
            await SubscriptionGateService(
                bot=self._bot, session=session, settings=self._settings
            ).clear_activation_message(chat_id=chat_id, message_id=message_id)
