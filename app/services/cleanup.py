"""Runtime cleanup service."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings, sqlite_database_path
from app.utils.time import utc_now


class RuntimeCleanupService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self) -> int:
        active_db = sqlite_database_path(self._settings.database_url)
        removed = 0
        for pattern in (
            "*.tmp",
            "*.bak",
            "*.log",
            "*.db-journal",
            "*.db-wal",
            "*.db-shm",
        ):
            for path in Path.cwd().glob(f"**/{pattern}"):
                if (
                    path.resolve() == active_db
                    or "alembic" in path.parts
                    or ".git" in path.parts
                ):
                    continue
                try:
                    if (
                        path.suffix == ".log"
                        and (utc_now().timestamp() - path.stat().st_mtime) < 14 * 86400
                    ):
                        continue
                    path.unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    continue
        return removed
