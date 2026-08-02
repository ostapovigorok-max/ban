"""Telegram API helpers."""

from __future__ import annotations

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMember, ChatPermissions


def muted_permissions() -> ChatPermissions:
    return ChatPermissions(can_send_messages=False)


def unrestricted_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )


def is_subscription_member(member: ChatMember) -> bool:
    status = getattr(member, "status", None)
    return status in {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
    }


async def is_chat_administrator(bot: Bot, chat_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(chat_id, user_id)
    status = getattr(member, "status", None)
    return status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}


def bot_can_moderate(member: ChatMember) -> bool:
    return bool(
        getattr(member, "can_delete_messages", False)
        and getattr(member, "can_restrict_members", False)
    )


async def has_moderation_permissions(bot: Bot, chat_id: int) -> bool:
    me = await bot.get_me()
    member = await bot.get_chat_member(chat_id, me.id)
    return bot_can_moderate(member)
