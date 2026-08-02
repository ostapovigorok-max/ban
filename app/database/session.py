"""Async SQLAlchemy session factory."""

from __future__ import annotations

import logging

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import sqlite_database_path

logger = logging.getLogger(__name__)


def create_sqlalchemy_engine(database_url: str) -> AsyncEngine:
    path = sqlite_database_path(database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(database_url, future=True, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        for pragma in [
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=10000",
            "PRAGMA temp_store=MEMORY",
        ]:
            cursor.execute(pragma)
        cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def log_database_diagnostics(engine: AsyncEngine, database_url: str) -> None:
    async with engine.connect() as connection:
        database_list = (await connection.execute(text("PRAGMA database_list"))).all()
        table_info = (
            await connection.execute(text("PRAGMA table_info(punishments)"))
        ).all()
        revision = None
        try:
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one_or_none()
        except Exception:
            revision = None
    logger.info(
        "database_startup_diagnostics",
        extra={
            "resolved_database_url": database_url,
            "sqlite_file_path": str(sqlite_database_path(database_url)),
            "database_schema_revision": revision,
            "pragma_database_list": [tuple(row) for row in database_list],
            "pragma_table_info_punishments": [tuple(row) for row in table_info],
        },
    )
