"""Structured logging setup."""

from __future__ import annotations

import gzip
import json
import logging
import logging.handlers
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord(
                "", 0, "", 0, "", (), None
            ).__dict__ and key not in {"message", "asctime"}:
                try:
                    json.dumps(value)
                    data[key] = value
                except TypeError:
                    data[key] = str(value)
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


class GZipRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def doRollover(self) -> None:
        super().doRollover()
        for index in range(self.backupCount, 0, -1):
            path = Path(f"{self.baseFilename}.{index}")
            gz_path = Path(f"{path}.gz")
            if path.exists() and not gz_path.exists():
                with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                path.unlink(missing_ok=True)


def configure_logging(level: str) -> None:
    Path("logs").mkdir(exist_ok=True)
    formatter = JsonFormatter()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    file_handler = GZipRotatingFileHandler(
        "logs/bot.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(stream)
    root.addHandler(file_handler)
