"""Repository for community vote state."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vote import Vote, VoteSession, VoteSessionStatus


class VoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        callback_token: str,
        chat_id: int,
        offender_user_id: int,
        offender_display_name: str,
        offender_message_id: int,
        creator_user_id: int,
        creator_username: str | None,
        creator_display_name: str,
        votes_required: int,
        expires_at: datetime,
    ) -> VoteSession:
        session = VoteSession(
            callback_token=callback_token,
            chat_id=chat_id,
            offender_user_id=offender_user_id,
            offender_display_name=offender_display_name,
            offender_message_id=offender_message_id,
            creator_user_id=creator_user_id,
            creator_username=creator_username,
            creator_display_name=creator_display_name,
            votes_required=votes_required,
            expires_at=expires_at,
        )
        self._session.add(session)
        await self._session.flush()
        return session

    async def get_by_id(self, session_id: int) -> VoteSession | None:
        return await self._session.get(VoteSession, session_id)

    async def get_by_token(self, callback_token: str) -> VoteSession | None:
        statement = select(VoteSession).where(
            VoteSession.callback_token == callback_token
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_active_for_offender(
        self, *, chat_id: int, offender_user_id: int
    ) -> VoteSession | None:
        statement = select(VoteSession).where(
            VoteSession.chat_id == chat_id,
            VoteSession.offender_user_id == offender_user_id,
            VoteSession.status == VoteSessionStatus.ACTIVE,
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def add_vote(self, *, session_id: int, voter_user_id: int) -> bool:
        self._session.add(Vote(session_id=session_id, voter_user_id=voter_user_id))
        try:
            await self._session.flush()
        except IntegrityError:
            return False
        return True

    async def increment_if_active(
        self, *, session_id: int, now: datetime
    ) -> int | None:
        statement = (
            update(VoteSession)
            .where(
                VoteSession.id == session_id,
                VoteSession.status == VoteSessionStatus.ACTIVE,
                VoteSession.expires_at > now,
            )
            .values(votes_count=VoteSession.votes_count + 1)
            .returning(VoteSession.votes_count)
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def set_voting_message_id(
        self, vote_session: VoteSession, message_id: int
    ) -> None:
        vote_session.voting_message_id = message_id
        await self._session.flush()

    async def mark_status_if_active(
        self, *, session_id: int, status: VoteSessionStatus
    ) -> bool:
        statement = (
            update(VoteSession)
            .where(
                VoteSession.id == session_id,
                VoteSession.status == VoteSessionStatus.ACTIVE,
            )
            .values(status=status)
        )
        result = cast(Any, await self._session.execute(statement))
        rowcount = int(result.rowcount)
        return rowcount == 1

    async def list_due(self, now: datetime) -> list[VoteSession]:
        statement = select(VoteSession).where(
            VoteSession.status == VoteSessionStatus.ACTIVE,
            VoteSession.expires_at <= now,
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def list_future(self, now: datetime) -> list[VoteSession]:
        statement = select(VoteSession).where(
            VoteSession.status == VoteSessionStatus.ACTIVE, VoteSession.expires_at > now
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def list_ready(self) -> list[VoteSession]:
        statement = select(VoteSession).where(
            VoteSession.status == VoteSessionStatus.ACTIVE,
            VoteSession.votes_count >= VoteSession.votes_required,
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def count_votes(self, session_id: int) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(Vote)
                    .where(Vote.session_id == session_id)
                )
            ).scalar_one()
        )
