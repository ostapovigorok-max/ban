"""Business operations for global community moderation votes."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.keyboards.community_vote import community_vote_keyboard
from app.models.errors import ActivationRequiredError, ModerationError
from app.models.vote import VoteSession, VoteSessionStatus
from app.repositories.votes import VoteRepository
from app.services.messages import TEXTS, ModerationTexts
from app.services.moderation import ModerationService
from app.services.rate_limit import community_vote_limiter
from app.services.subscription import SubscriptionGateService
from app.services.types import ModerationRequest
from app.utils.html import user_mention
from app.utils.locks import KeyedLockRegistry
from app.utils.time import as_utc, utc_now

logger = logging.getLogger(__name__)
_vote_locks = KeyedLockRegistry()
VOTE_DURATION_MINUTES = 60
VOTES_REQUIRED = 20


@dataclass(frozen=True, slots=True)
class VoteCastResult:
    accepted: bool
    completed: bool
    alert: str | None = None


class CommunityVoteService:
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
        self._settings = settings
        self._texts = texts
        self._repository = VoteRepository(session)
        self._moderation = ModerationService(
            bot=bot, session=session, settings=settings, texts=texts
        )

    async def start_vote(self, request: ModerationRequest) -> VoteSession:
        await self._moderation.validate_community_vote_target(
            chat_id=request.chat_id, target_user_id=request.target_user_id
        )
        existing = await self._repository.get_active_for_offender(
            chat_id=request.chat_id, offender_user_id=request.target_user_id
        )
        if existing is not None:
            if as_utc(existing.expires_at) > utc_now():
                raise ModerationError(self._texts.vote_already_active)
            await self.expire_vote_session(existing)
        try:
            vote_session = await self._repository.create_session(
                callback_token=secrets.token_urlsafe(16),
                chat_id=request.chat_id,
                offender_user_id=request.target_user_id,
                offender_display_name=request.target_display_name,
                offender_message_id=request.offending_message_id,
                creator_user_id=request.admin_id,
                creator_username=request.admin_username,
                creator_display_name=request.admin_display_name,
                votes_required=VOTES_REQUIRED,
                expires_at=utc_now() + timedelta(minutes=VOTE_DURATION_MINUTES),
            )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ModerationError(self._texts.vote_already_active) from exc
        message = await self._send_vote_message(vote_session)
        if message is None:
            await self._repository.mark_status_if_active(
                session_id=vote_session.id, status=VoteSessionStatus.EXPIRED
            )
            await self._session.commit()
            raise ModerationError(self._texts.vote_failed)
        await self._repository.set_voting_message_id(vote_session, message.message_id)
        await self._session.commit()
        return vote_session

    async def cast_vote(
        self, *, callback_token: str, voter_user_id: int
    ) -> VoteCastResult:
        vote_session = await self._repository.get_by_token(callback_token)
        if vote_session is None:
            return VoteCastResult(False, False, self._texts.action_unavailable)
        if not await community_vote_limiter.allow(vote_session.chat_id):
            return VoteCastResult(False, False, self._texts.community_vote_rate_limited)
        async with _vote_locks.lock(vote_session.id):
            return await self._cast_vote_locked(
                callback_token=callback_token, voter_user_id=voter_user_id
            )

    async def _cast_vote_locked(
        self, *, callback_token: str, voter_user_id: int
    ) -> VoteCastResult:
        vote_session = await self._repository.get_by_token(callback_token)
        if vote_session is None or vote_session.status != VoteSessionStatus.ACTIVE:
            return VoteCastResult(False, False, self._texts.action_unavailable)
        if not await self._ensure_group_active(vote_session.chat_id):
            return VoteCastResult(False, False, self._texts.activation_required)
        if as_utc(vote_session.expires_at) <= utc_now():
            await self.expire_vote_session(vote_session)
            return VoteCastResult(False, False, self._texts.action_unavailable)
        inserted = await self._repository.add_vote(
            session_id=vote_session.id, voter_user_id=voter_user_id
        )
        if not inserted:
            await self._session.rollback()
            return VoteCastResult(False, False, self._texts.vote_duplicate)
        new_count = await self._repository.increment_if_active(
            session_id=vote_session.id, now=utc_now()
        )
        if new_count is None:
            await self._session.rollback()
            return VoteCastResult(False, False, self._texts.action_unavailable)
        await self._session.commit()
        await self._session.refresh(vote_session)
        await self._edit_vote_message(vote_session, votes_count=new_count)
        if new_count >= vote_session.votes_required:
            completed = await self._complete_vote_session_locked(vote_session.id)
            return VoteCastResult(
                True, completed, None if completed else self._texts.vote_failed
            )
        return VoteCastResult(True, False)

    async def complete_vote_session(self, vote_session_id: int) -> bool:
        async with _vote_locks.lock(vote_session_id):
            return await self._complete_vote_session_locked(vote_session_id)

    async def _complete_vote_session_locked(self, vote_session_id: int) -> bool:
        vote_session = await self._repository.get_by_id(vote_session_id)
        if (
            vote_session is None
            or vote_session.status != VoteSessionStatus.ACTIVE
            or vote_session.votes_count < vote_session.votes_required
        ):
            return False
        if not await self._ensure_group_active(vote_session.chat_id):
            return False
        if not await self._moderation.reconcile_active_punishment(
            vote_session.chat_id, vote_session.offender_user_id
        ):
            await self._moderation.apply_restriction(
                ModerationRequest(
                    chat_id=vote_session.chat_id,
                    command_message_id=vote_session.offender_message_id,
                    offending_message_id=vote_session.offender_message_id,
                    admin_id=vote_session.creator_user_id,
                    admin_username=vote_session.creator_username,
                    admin_display_name=vote_session.creator_display_name,
                    target_user_id=vote_session.offender_user_id,
                    target_display_name=vote_session.offender_display_name,
                ),
                require_moderator=False,
                delete_command_message=False,
            )
        if not await self._repository.mark_status_if_active(
            session_id=vote_session.id, status=VoteSessionStatus.COMPLETED
        ):
            await self._session.rollback()
            return False
        await self._session.commit()
        await self._disable_vote_button(vote_session)
        await self._edit_vote_message(
            vote_session, votes_count=vote_session.votes_count, completed=True
        )
        return True

    async def expire_vote_session_by_id(self, vote_session_id: int) -> bool:
        async with _vote_locks.lock(vote_session_id):
            vote_session = await self._repository.get_by_id(vote_session_id)
            if (
                vote_session is None
                or vote_session.status != VoteSessionStatus.ACTIVE
                or as_utc(vote_session.expires_at) > utc_now()
            ):
                return False
            return await self.expire_vote_session(vote_session)

    async def expire_due_vote_sessions(self) -> int:
        count = 0
        for session in await self._repository.list_due(utc_now()):
            if await self.expire_vote_session_by_id(session.id):
                count += 1
        return count

    async def complete_ready_vote_sessions(self) -> int:
        count = 0
        for session in await self._repository.list_ready():
            if await self.complete_vote_session(session.id):
                count += 1
        return count

    async def expire_vote_session(self, vote_session: VoteSession) -> bool:
        if not await self._repository.mark_status_if_active(
            session_id=vote_session.id, status=VoteSessionStatus.EXPIRED
        ):
            await self._session.rollback()
            return False
        await self._session.commit()
        await self._disable_vote_button(vote_session)
        await self._edit_vote_message(
            vote_session, votes_count=vote_session.votes_count, expired=True
        )
        return True

    async def _send_vote_message(self, vote_session: VoteSession) -> Message | None:
        try:
            return await self._bot.send_message(
                chat_id=vote_session.chat_id,
                text=self._vote_text(vote_session, votes_count=0),
                reply_markup=community_vote_keyboard(
                    callback_token=vote_session.callback_token,
                    votes_count=0,
                    votes_required=vote_session.votes_required,
                ),
            )
        except TelegramAPIError:
            return None

    async def _edit_vote_message(
        self,
        vote_session: VoteSession,
        *,
        votes_count: int,
        completed: bool = False,
        expired: bool = False,
    ) -> None:
        if vote_session.voting_message_id is None:
            return
        if completed:
            text = self._texts.community_vote_completed.format(
                votes_count=votes_count, votes_required=vote_session.votes_required
            )
            reply_markup = None
        elif expired:
            text = self._texts.community_vote_expired.format(
                votes_count=votes_count, votes_required=vote_session.votes_required
            )
            reply_markup = None
        else:
            text = self._vote_text(vote_session, votes_count=votes_count)
            reply_markup = community_vote_keyboard(
                callback_token=vote_session.callback_token,
                votes_count=votes_count,
                votes_required=vote_session.votes_required,
            )
        try:
            await self._bot.edit_message_text(
                chat_id=vote_session.chat_id,
                message_id=vote_session.voting_message_id,
                text=text,
                reply_markup=reply_markup,
            )
        except (TelegramBadRequest, TelegramAPIError):
            logger.info(
                "community_vote_message_edit_failed",
                extra={"vote_session_id": vote_session.id},
                exc_info=True,
            )

    async def _disable_vote_button(self, vote_session: VoteSession) -> None:
        if vote_session.voting_message_id is not None:
            try:
                await self._bot.edit_message_reply_markup(
                    chat_id=vote_session.chat_id,
                    message_id=vote_session.voting_message_id,
                    reply_markup=None,
                )
            except TelegramAPIError:
                logger.info(
                    "community_vote_button_disable_failed",
                    extra={"vote_session_id": vote_session.id},
                    exc_info=True,
                )

    def _vote_text(self, vote_session: VoteSession, *, votes_count: int) -> str:
        return self._texts.community_vote_started.format(
            mention=user_mention(
                user_id=vote_session.offender_user_id,
                display_name=vote_session.offender_display_name,
            ),
            days=self._settings.restriction_days,
            votes_count=votes_count,
            votes_required=vote_session.votes_required,
            minutes=VOTE_DURATION_MINUTES,
        )

    async def _ensure_group_active(self, chat_id: int) -> bool:
        try:
            await SubscriptionGateService(
                bot=self._bot,
                session=self._session,
                settings=self._settings,
                texts=self._texts,
            ).ensure_active(chat_id)
        except ActivationRequiredError:
            return False
        return True
