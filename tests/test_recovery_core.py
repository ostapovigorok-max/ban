"""Regression checks for the recovered moderation bot sources."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from aiogram.types import InlineKeyboardMarkup
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alembic import command
from app.config.settings import Settings
from app.database.base import Base
from app.database.session import create_session_factory, create_sqlalchemy_engine
from app.keyboards.subscription import SubscriptionCallback, subscription_keyboard
from app.models import GroupActivation, Punishment, Vote, VoteSession
from app.repositories.votes import VoteRepository
from app.services.subscription import SubscriptionGateService
from app.utils.time import utc_now

_ = (GroupActivation, Punishment, Vote, VoteSession)


@dataclass(slots=True)
class FakeMessage:
    message_id: int


class FakeBot:
    def __init__(self) -> None:
        self.sent_chat_ids: list[int] = []
        self.edited_chat_ids: list[int] = []
        self.fail_edit = False
        self.next_message_id = 100

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup,
        disable_web_page_preview: bool,
    ) -> FakeMessage:
        assert disable_web_page_preview is True
        assert text
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
        reply_markup: InlineKeyboardMarkup,
        disable_web_page_preview: bool,
    ) -> None:
        assert message_id
        assert text
        assert reply_markup.inline_keyboard
        assert disable_web_page_preview is True
        self.edited_chat_ids.append(chat_id)
        if self.fail_edit:
            raise RuntimeError("message is gone")


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
