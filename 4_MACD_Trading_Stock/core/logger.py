"""Rotating file logger for the trading bot."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "trading.log"

_FILE_HANDLER: RotatingFileHandler | None = None
_STREAM_HANDLER: logging.StreamHandler | None = None


def setup_logger(level: str = "INFO", console: bool | None = None) -> logging.Logger:
    """Configure and return the application logger."""
    global _FILE_HANDLER, _STREAM_HANDLER

    if console is None:
        console = os.environ.get("LOG_CONSOLE", "").lower() in {"1", "true", "yes"}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("srp_dhan_bot")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")

    if _FILE_HANDLER is None:
        _FILE_HANDLER = RotatingFileHandler(
            LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        _FILE_HANDLER.setFormatter(formatter)
        logger.addHandler(_FILE_HANDLER)
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
    logger = logging.getLogger("srp_dhan_bot")
    if not logger.handlers:
        return setup_logger(console=False)
    return logger


def flush_logger() -> None:
    """Flush all logger handlers."""
    logger = get_logger()
    for handler in logger.handlers:
        handler.flush()
