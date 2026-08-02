"""Environment-driven application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from re import fullmatch
from urllib.parse import unquote, urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/moderation.db"
REQUIRED_CHAT_URL = "https://t.me/+whQxcuFoU5JjNjMy"
REQUIRED_CHANNEL_URL = "https://t.me/+0WkJZOFWQEEwZWM6"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL, validation_alias="DATABASE_URL"
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.startswith("sqlite+aiosqlite:///"):
            raise ValueError("DATABASE_URL must use the sqlite+aiosqlite driver.")
        url = make_url(normalized)
        database = url.database
        if database is None or database in {"", ":memory:"}:
            raise ValueError("DATABASE_URL must reference a persistent SQLite file.")
        path = Path(unquote(database))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return str(url.set(database=path.resolve().as_posix()))


class Settings(DatabaseSettings):
    bot_token: SecretStr = Field(validation_alias="BOT_TOKEN")
    moderation_command: str = Field(
        default="/ban", validation_alias="MODERATION_COMMAND"
    )
    rules_url: str = Field(
        default="https://telegra.ph/Pravila-chatu-Troyeshchina-08-01",
        validation_alias="RULES_URL",
    )
    restriction_days: int = Field(default=7, validation_alias="RESTRICTION_DAYS")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    required_chat_id: int = Field(validation_alias="REQUIRED_CHAT_ID")
    required_channel_id: int = Field(validation_alias="REQUIRED_CHANNEL_ID")
    required_chat_url: str = Field(
        default=REQUIRED_CHAT_URL, validation_alias="REQUIRED_CHAT_URL"
    )
    required_channel_url: str = Field(
        default=REQUIRED_CHANNEL_URL, validation_alias="REQUIRED_CHANNEL_URL"
    )

    @field_validator("moderation_command")
    @classmethod
    def validate_moderation_command(cls, value: str) -> str:
        normalized = value.strip().lower()
        if fullmatch(r"/[a-z0-9_]{1,32}", normalized) is None:
            raise ValueError("MODERATION_COMMAND must be a slash-prefixed command.")
        return normalized

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("BOT_TOKEN must not be empty.")
        return value

    @field_validator("rules_url", "required_chat_url", "required_channel_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL values must be absolute HTTP(S) URLs.")
        return value

    @field_validator("restriction_days")
    @classmethod
    def validate_restriction_days(cls, value: int) -> int:
        if not 1 <= value <= 365:
            raise ValueError("RESTRICTION_DAYS must be between 1 and 365.")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be a standard Python logging level.")
        return normalized

    @field_validator("required_chat_id", "required_channel_id", mode="before")
    @classmethod
    def validate_required_telegram_id(cls, value: object) -> int:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError("required subscription IDs must be configured.")
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.startswith(("http://", "https://", "t.me/", "@")):
                raise ValueError(
                    "required subscription IDs must be numeric, not links or usernames."
                )
            if fullmatch(r"-?\d+", normalized) is None:
                raise ValueError(
                    "required subscription IDs must be Telegram numeric IDs."
                )
            value = int(normalized)
        if not isinstance(value, int) or value == 0:
            raise ValueError("required subscription IDs must be non-zero integers.")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def get_database_url() -> str:
    return DatabaseSettings().database_url


def sqlite_database_path(database_url: str) -> Path:
    database = make_url(database_url).database
    if database is None:
        raise ValueError("DATABASE_URL must reference a SQLite file.")
    return Path(unquote(database)).resolve()
