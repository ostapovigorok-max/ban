"""Domain errors with safe user-facing messages."""


class ModerationError(Exception):
    """Expected moderation failure that can be shown to a chat user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class ActivationRequiredError(ModerationError):
    """Raised after an inactive group has been given an activation prompt."""
