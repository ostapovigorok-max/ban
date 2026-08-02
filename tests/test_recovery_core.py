"""Regression checks for the recovered moderation bot sources."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import (
    Chat,
    ChatMemberRestricted,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    User,
)
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.config.settings import Settings
from app.database.base import Base
from app.database.session import create_session_factory, create_sqlalchemy_engine
from app.handlers.callbacks import _answer_release_contact, _is_bot_start_url
from app.keyboards.restriction import release_restriction_keyboard
from app.keyboards.subscription import SubscriptionCallback, subscription_keyboard
from app.models.punishment import PunishmentStatus
from app.models import GroupActivation, Punishment, Vote, VoteSession
from app.repositories.punishments import PunishmentRepository
from app.repositories.votes import VoteRepository
from app.services.community_vote import CommunityVoteService
from app.services.messages import TEXTS
from app.services.moderation import ModerationService
from app.services.types import CallbackResultKind, ModerationRequest
from app.services.subscription import SubscriptionGateService
from app.utils.telegram import is_chat_member_restricted
from app.utils.time import utc_now

_ = (GroupActivation, Punishment, Vote, VoteSession)


@dataclass(slots=True)
class FakeMessage:
    message_id: int


@dataclass(slots=True)
class FakeCallbackAnswer:
    url: str | None = None
    text: str | None = None
    show_alert: bool | None = None


@dataclass(slots=True)
class FakeChatMember:
    status: ChatMemberStatus
    can_delete_messages: bool = False
    can_restrict_members: bool = False


@dataclass(slots=True)
class FakeUser:
    id: int
    username: str | None = None
    full_name: str = "Test Bot"


class FakeBot:
    def __init__(self) -> None:
        self.sent_chat_ids: list[int] = []
        self.edited_chat_ids: list[int] = []
        self.fail_edit = False
        self.next_message_id = 100
        self.me = FakeUser(id=999, username="moderation_bot", full_name="Moderation Bot")
        self.members: dict[tuple[int, int], FakeChatMember] = {}
        self.moderation_permissions: dict[int, bool] = {}
        self.restriction_calls: list[tuple[int, int, bool]] = []

    def set_member(
        self,
        *,
        chat_id: int,
        user_id: int,
        status: ChatMemberStatus,
        can_delete_messages: bool = False,
        can_restrict_members: bool = False,
    ) -> None:
        self.members[(chat_id, user_id)] = FakeChatMember(
            status=status,
            can_delete_messages=can_delete_messages,
            can_restrict_members=can_restrict_members,
        )

    def set_restricted(
        self, *, chat_id: int, user_id: int, restricted: bool = True
    ) -> None:
        if restricted:
            self.set_member(
                chat_id=chat_id,
                user_id=user_id,
                status=ChatMemberStatus.RESTRICTED,
            )
        else:
            self.set_member(
                chat_id=chat_id,
                user_id=user_id,
                status=ChatMemberStatus.MEMBER,
            )

    def set_bot_moderation_permissions(self, *, chat_id: int, allowed: bool) -> None:
        self.moderation_permissions[chat_id] = allowed

    async def get_me(self) -> FakeUser:
        return self.me

    async def get_chat_member(self, chat_id: int, user_id: int) -> FakeChatMember:
        if user_id == self.me.id:
            if not self.moderation_permissions.get(chat_id, True):
                return FakeChatMember(
                    status=ChatMemberStatus.ADMINISTRATOR,
                    can_delete_messages=False,
                    can_restrict_members=False,
                )
            return FakeChatMember(
                status=ChatMemberStatus.ADMINISTRATOR,
                can_delete_messages=True,
                can_restrict_members=True,
            )
        return self.members.get(
            (chat_id, user_id), FakeChatMember(status=ChatMemberStatus.MEMBER)
        )

    async def restrict_chat_member(
        self,
        *,
        chat_id: int,
        user_id: int,
        permissions,
        until_date=None,
        use_independent_chat_permissions: bool | None = None,
    ) -> None:
        self.restriction_calls.append((chat_id, user_id, permissions.can_send_messages))
        if permissions.can_send_messages:
            self.set_member(
                chat_id=chat_id,
                user_id=user_id,
                status=ChatMemberStatus.MEMBER,
            )
        else:
            self.set_member(
                chat_id=chat_id,
                user_id=user_id,
                status=ChatMemberStatus.RESTRICTED,
            )

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
        disable_web_page_preview: bool = True,
    ) -> FakeMessage:
        assert disable_web_page_preview is True
        assert text
        if reply_markup is not None:
            assert reply_markup.inline_keyboard
        self.sent_chat_ids.append(chat_id)
        self.next_message_id += 1
        return FakeMessage(self.next_message_id)

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None,
        disable_web_page_preview: bool = True,
    ) -> None:
        assert message_id
        assert text
        if reply_markup is not None:
            assert reply_markup.inline_keyboard
        assert disable_web_page_preview is True
        self.edited_chat_ids.append(chat_id)
        if self.fail_edit:
            raise RuntimeError("message is gone")

    async def edit_message_reply_markup(
        self,
        *,
        chat_id: int,
        message_id: int,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> None:
        assert chat_id
        assert message_id
        self.edited_chat_ids.append(chat_id)

    async def delete_message(self, *, chat_id: int, message_id: int) -> None:
        assert chat_id
        assert message_id


class FakeCallback:
    def __init__(self) -> None:
        self.answers: list[FakeCallbackAnswer] = []

    async def answer(
        self,
        text: str | None = None,
        *,
        show_alert: bool = False,
        url: str | None = None,
    ) -> None:
        self.answers.append(
            FakeCallbackAnswer(url=url, text=text, show_alert=show_alert)
        )


def _make_moderation_request(*, chat_id: int, target_user_id: int) -> ModerationRequest:
    return ModerationRequest(
        chat_id=chat_id,
        command_message_id=10,
        offending_message_id=11,
        admin_id=1,
        admin_username="admin",
        admin_display_name="Admin",
        target_user_id=target_user_id,
        target_display_name="Target",
    )


def _make_restricted_member(*, can_send_messages: bool) -> ChatMemberRestricted:
    return ChatMemberRestricted(
        status=ChatMemberStatus.RESTRICTED,
        user=User(id=42, is_bot=False, first_name="Target"),
        is_member=True,
        can_send_messages=can_send_messages,
        can_send_audios=can_send_messages,
        can_send_documents=can_send_messages,
        can_send_photos=can_send_messages,
        can_send_videos=can_send_messages,
        can_send_video_notes=can_send_messages,
        can_send_voice_notes=can_send_messages,
        can_send_polls=can_send_messages,
        can_send_other_messages=can_send_messages,
        can_add_web_page_previews=can_send_messages,
        can_react_to_messages=True,
        can_edit_tag=True,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_manage_topics=True,
        until_date=utc_now(),
    )


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        BOT_TOKEN="123456:ABCDEF",
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'moderation.db'}",
        REQUIRED_CHAT_ID="-100111",
        REQUIRED_CHANNEL_ID="-100222",
        REQUIRED_CHAT_URL="https://t.me/+chat",
        REQUIRED_CHANNEL_URL="https://t.me/+channel",
    )


@pytest.fixture
def session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_sqlalchemy_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    try:
        yield create_session_factory(engine)
    finally:
        asyncio.run(engine.dispose())


def test_subscription_keyboard_contains_links_and_callback() -> None:
    keyboard = subscription_keyboard(
        chat_id=-100777,
        chat_url="https://t.me/+chat",
        channel_url="https://t.me/+channel",
    )

    assert keyboard.inline_keyboard[0][0].url == "https://t.me/+chat"
    assert keyboard.inline_keyboard[1][0].url == "https://t.me/+channel"
    callback_data = keyboard.inline_keyboard[2][0].callback_data
    assert callback_data is not None
    unpacked = SubscriptionCallback.unpack(callback_data)
    assert unpacked.chat_id == -100777
    assert unpacked.action == "verify"


def test_callback_redirect_rejects_admin_profile_url() -> None:
    assert not _is_bot_start_url(
        url="https://t.me/responsible_admin",
        bot_username="moderation_bot",
    )
    assert not _is_bot_start_url(
        url=None,
        bot_username="moderation_bot",
    )
    assert _is_bot_start_url(
        url="https://t.me/moderation_bot?start=release",
        bot_username="moderation_bot",
    )


def test_release_contact_redirects_to_admin_username_only() -> None:
    async def run() -> None:
        callback = FakeCallback()

        await _answer_release_contact(
            callback=callback,  # type: ignore[arg-type]
            punishment_id=12,
            admin_id=7,
            admin_username="responsible_admin",
        )

        assert callback.answers == [
            FakeCallbackAnswer(url="https://t.me/responsible_admin", show_alert=False)
        ]

    asyncio.run(run())


def test_release_contact_without_admin_username_shows_alert() -> None:
    async def run() -> None:
        callback = FakeCallback()

        await _answer_release_contact(
            callback=callback,  # type: ignore[arg-type]
            punishment_id=12,
            admin_id=7,
            admin_username=None,
        )

        assert callback.answers == [
            FakeCallbackAnswer(
                text=TEXTS.admin_contact_unavailable,
                show_alert=True,
            )
        ]

    asyncio.run(run())


def test_only_punishing_admin_can_release_punishment(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings(tmp_path)
    fake_bot = FakeBot()
    chat_id = -100777
    punished_user_id = 42
    punishing_admin_id = 7
    other_admin_id = 8
    fake_bot.set_bot_moderation_permissions(chat_id=chat_id, allowed=True)
    fake_bot.set_restricted(chat_id=chat_id, user_id=punished_user_id)
    for admin_id in (punishing_admin_id, other_admin_id):
        fake_bot.set_member(
            chat_id=chat_id,
            user_id=admin_id,
            status=ChatMemberStatus.ADMINISTRATOR,
        )

    async def run() -> None:
        async with session_factory() as session:
            repo = PunishmentRepository(session)
            punishment = await repo.create(
                chat_id=chat_id,
                user_id=punished_user_id,
                admin_id=punishing_admin_id,
                admin_username="responsible_admin",
                admin_display_name="Admin",
                user_display_name="Target",
                expires_at=utc_now() + timedelta(days=1),
            )
            await session.commit()

            service = ModerationService(
                bot=fake_bot,  # type: ignore[arg-type]
                session=session,
                settings=settings,
            )

            other_result = await service.handle_release_click(
                punishment_id=punishment.id,
                chat_id=chat_id,
                clicker_id=other_admin_id,
            )
            assert other_result.kind == CallbackResultKind.ALERT
            assert len(fake_bot.restriction_calls) == 0

            issuer_result = await service.handle_release_click(
                punishment_id=punishment.id,
                chat_id=chat_id,
                clicker_id=punishing_admin_id,
            )
            assert issuer_result.kind == CallbackResultKind.ANSWER
            assert fake_bot.restriction_calls == [(chat_id, punished_user_id, True)]

    asyncio.run(run())


def test_restriction_keyboard_uses_ukrainian_labels() -> None:
    keyboard = release_restriction_keyboard(
        12,
        rules_url="https://example.test/rules",
    )

    assert keyboard.inline_keyboard[0][0].text == "📖 Правила"
    assert keyboard.inline_keyboard[1][0].text == "🔓 Зняти обмеження"


def test_chat_member_updated_manual_unrestrict_is_not_active_punishment() -> None:
    restricted = _make_restricted_member(can_send_messages=False)
    restored = _make_restricted_member(can_send_messages=True)
    partial = ChatMemberRestricted(
        status=ChatMemberStatus.RESTRICTED,
        user=User(id=42, is_bot=False, first_name="Target"),
        is_member=True,
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=False,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_react_to_messages=True,
        can_edit_tag=True,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_manage_topics=True,
        until_date=utc_now(),
    )

    update = ChatMemberUpdated(
        chat=Chat(id=-100777, type=ChatType.SUPERGROUP, title="Test"),
        from_user=User(id=7, is_bot=False, first_name="Admin"),
        date=utc_now(),
        old_chat_member=restricted,
        new_chat_member=restored,
    )

    assert is_chat_member_restricted(update.old_chat_member)
    assert not is_chat_member_restricted(update.new_chat_member)
    assert is_chat_member_restricted(partial)


def test_settings_reject_invite_link_for_required_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="numeric"):
        Settings(
            BOT_TOKEN="123456:ABCDEF",
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path / 'moderation.db'}",
            REQUIRED_CHAT_ID="https://t.me/+chat",
            REQUIRED_CHANNEL_ID="-100222",
        )


def test_inactive_group_creates_activation_prompt_once(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings(tmp_path)
    fake_bot = FakeBot()

    async def run() -> None:
        async with session_factory() as session:
            service = SubscriptionGateService(
                bot=fake_bot,  # type: ignore[arg-type]
                session=session,
                settings=settings,
            )
            await service.send_prompt_if_needed(-100777)
            await service.send_prompt_if_needed(-100777)

    asyncio.run(run())

    assert fake_bot.sent_chat_ids == [-100777]
    assert fake_bot.edited_chat_ids == [-100777]
    assert settings.required_chat_id not in fake_bot.sent_chat_ids
    assert settings.required_channel_id not in fake_bot.sent_chat_ids


def test_vote_unique_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        async with session_factory() as session:
            repo = VoteRepository(session)
            vote_session = await repo.create_session(
                callback_token="secure-token",
                chat_id=-100777,
                offender_user_id=42,
                offender_display_name="Ніна",
                offender_message_id=5,
                creator_user_id=7,
                creator_username=None,
                creator_display_name="Олена",
                votes_required=20,
                expires_at=utc_now(),
            )
            assert await repo.add_vote(session_id=vote_session.id, voter_user_id=10)
            assert not await repo.add_vote(session_id=vote_session.id, voter_user_id=10)

    asyncio.run(run())


def test_stale_punishment_is_reconciled_before_ban_and_vote_creation(
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings(tmp_path)
    fake_bot = FakeBot()
    chat_id = -100777
    user_id = 42
    admin_id = 7
    fake_bot.set_bot_moderation_permissions(chat_id=chat_id, allowed=True)
    fake_bot.set_restricted(chat_id=chat_id, user_id=user_id, restricted=False)
    fake_bot.set_member(
        chat_id=chat_id,
        user_id=admin_id,
        status=ChatMemberStatus.ADMINISTRATOR,
    )

    async def run() -> None:
        async with session_factory() as session:
            session.add(
                GroupActivation(
                    chat_id=chat_id,
                    is_active=True,
                    activating_admin_id=admin_id,
                    activating_admin_name="Admin",
                )
            )
            await session.commit()

            moderation = ModerationService(
                bot=fake_bot,  # type: ignore[arg-type]
                session=session,
                settings=settings,
            )
            votes = CommunityVoteService(
                bot=fake_bot,  # type: ignore[arg-type]
                session=session,
                settings=settings,
            )

            request = _make_moderation_request(chat_id=chat_id, target_user_id=user_id)
            request = ModerationRequest(
                chat_id=request.chat_id,
                command_message_id=request.command_message_id,
                offending_message_id=request.offending_message_id,
                admin_id=admin_id,
                admin_username=request.admin_username,
                admin_display_name=request.admin_display_name,
                target_user_id=request.target_user_id,
                target_display_name=request.target_display_name,
            )

            first_punishment = await moderation.apply_restriction(request)
            assert first_punishment.status == PunishmentStatus.ACTIVE

            fake_bot.set_restricted(chat_id=chat_id, user_id=user_id, restricted=False)

            second_punishment = await moderation.apply_restriction(request)
            assert second_punishment.id != first_punishment.id
            assert second_punishment.status == PunishmentStatus.ACTIVE

            repo = PunishmentRepository(session)
            active = await repo.get_active_for_user(chat_id=chat_id, user_id=user_id)
            assert active is not None
            assert active.id == second_punishment.id

            punishments = (
                await session.execute(
                    select(Punishment).where(
                        Punishment.chat_id == chat_id,
                        Punishment.user_id == user_id,
                    )
                )
            ).scalars().all()
            assert len(punishments) == 2
            assert {p.status for p in punishments} == {
                PunishmentStatus.EXPIRED,
                PunishmentStatus.ACTIVE,
            }

            fake_bot.set_restricted(chat_id=chat_id, user_id=user_id, restricted=False)

            vote_session = await votes.start_vote(request)
            assert vote_session.offender_user_id == user_id

            refreshed = await repo.get_active_for_user(chat_id=chat_id, user_id=user_id)
            assert refreshed is None

            punishments = (
                await session.execute(
                    select(Punishment).where(
                        Punishment.chat_id == chat_id,
                        Punishment.user_id == user_id,
                    )
                )
            ).scalars().all()
            assert [p.status for p in punishments].count(PunishmentStatus.EXPIRED) == 2
            assert all(p.status != PunishmentStatus.ACTIVE for p in punishments)

    asyncio.run(run())


def test_alembic_upgrade_head_from_empty_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

    assert {
        "alembic_version",
        "punishments",
        "vote_sessions",
        "votes",
        "group_activations",
    } <= actual_tables
