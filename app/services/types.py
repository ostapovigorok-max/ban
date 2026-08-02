"""Service DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ModerationRequest:
    chat_id: int
    command_message_id: int
    offending_message_id: int
    admin_id: int
    admin_username: str | None
    admin_display_name: str
    target_user_id: int
    target_display_name: str


class CallbackResultKind(StrEnum):
    ANSWER = "ANSWER"
    ALERT = "ALERT"
    URL = "URL"


@dataclass(frozen=True, slots=True)
class CallbackResult:
    kind: CallbackResultKind
    text: str | None = None
    url: str | None = None
