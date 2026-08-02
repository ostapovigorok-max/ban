"""Inline controls for global community voting."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class CommunityVoteCallback(CallbackData, prefix="community-vote"):
    token: str


def community_vote_keyboard(
    *, callback_token: str, votes_count: int, votes_required: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"?? ?????????? ({votes_count}/{votes_required})",
                    callback_data=CommunityVoteCallback(token=callback_token).pack(),
                )
            ]
        ]
    )
