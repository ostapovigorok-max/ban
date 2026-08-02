"""Inline controls for subscription-gate activation."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class SubscriptionCallback(CallbackData, prefix="subscription"):
    action: str
    chat_id: int


def subscription_keyboard(
    *, chat_id: int, chat_url: str, channel_url: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Чат", url=chat_url)],
            [InlineKeyboardButton(text="📢 Канал", url=channel_url)],
            [
                InlineKeyboardButton(
                    text="✅ Перевірити підписку",
                    callback_data=SubscriptionCallback(
                        action="verify",
                        chat_id=chat_id,
                    ).pack(),
                )
            ],
        ]
    )
