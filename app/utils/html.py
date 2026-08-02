"""HTML helpers."""

from __future__ import annotations

from html import escape


def user_mention(*, user_id: int, display_name: str) -> str:
    name = escape(display_name or "??????????", quote=True)
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def escaped_url(url: str) -> str:
    return escape(url, quote=True)
