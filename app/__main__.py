"""Module entrypoint for ``python -m app``."""

from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError

from app.bot.lifecycle import run_bot
from app.config.settings import get_settings


def main() -> None:
    """Start the Telegram moderation bot."""

    try:
        settings = get_settings()
    except ValidationError as exc:
        logging.basicConfig(level=logging.CRITICAL)
        logging.critical("configuration_validation_failed: %s", exc)
        raise SystemExit(1) from exc

    try:
        asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
