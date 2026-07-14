"""Daily dated file logger for the Long Straddle Supertrend bot."""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"

_FILE_HANDLER: logging.FileHandler | None = None
_STREAM_HANDLER: logging.StreamHandler | None = None
_LOG_DATE: str | None = None


def get_log_file_path(for_date: date | None = None) -> Path:
    """Return path for the daily log file."""
    day = for_date or date.today()
    return LOG_DIR / f"{day.isoformat()}.log"


def latest_log_file() -> Path:
    """Return the newest dated log file, or today's path if none exist."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    dated = sorted(LOG_DIR.glob("????-??-??.log"))
    if dated:
        return dated[-1]
    return get_log_file_path()


def setup_logger(level: str = "INFO", console: bool | None = None) -> logging.Logger:
    """Configure and return the application logger with a daily log file."""
    global _FILE_HANDLER, _STREAM_HANDLER, _LOG_DATE

    if console is None:
        console = os.environ.get("LOG_CONSOLE", "").lower() in {"1", "true", "yes"}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("srp_supertrend_straddle")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")
    today = date.today().isoformat()
    log_path = get_log_file_path()

    if _FILE_HANDLER is None or _LOG_DATE != today:
        if _FILE_HANDLER is not None:
            logger.removeHandler(_FILE_HANDLER)
            _FILE_HANDLER.close()
        _FILE_HANDLER = logging.FileHandler(log_path, encoding="utf-8")
        _FILE_HANDLER.setFormatter(formatter)
        logger.addHandler(_FILE_HANDLER)
        _LOG_DATE = today
    else:
        _FILE_HANDLER.setFormatter(formatter)

    if console and _STREAM_HANDLER is None:
        _STREAM_HANDLER = logging.StreamHandler()
        _STREAM_HANDLER.setFormatter(formatter)
        logger.addHandler(_STREAM_HANDLER)
    elif not console and _STREAM_HANDLER is not None:
        logger.removeHandler(_STREAM_HANDLER)
        _STREAM_HANDLER = None

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


def get_logger() -> logging.Logger:
    """Return the application logger, creating it if needed."""
    logger = logging.getLogger("srp_supertrend_straddle")
    if not logger.handlers:
        return setup_logger(console=False)
    return logger
