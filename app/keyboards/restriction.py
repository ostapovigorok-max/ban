"""Inline keyboard and callback data for punishment controls."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class RestrictionCallback(CallbackData, prefix="restriction"):
    action: str
    punishment_id: int


def rules_keyboard(rules_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📖 Правила", url=rules_url)]]
    )


def release_restriction_keyboard(
    punishment_id: int, *, rules_url: str
) -> InlineKeyboardMarkup:
    callback_data = RestrictionCallback(
        action="release", punishment_id=punishment_id
    ).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📖 Правила", url=rules_url)],
            [
                InlineKeyboardButton(
                    text="🔓 Зняти обмеження", callback_data=callback_data
                )
            ],
        ]
    )
