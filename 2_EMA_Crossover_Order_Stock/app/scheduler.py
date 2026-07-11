"""Polling scheduler with efficient sleep-based loop."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from app.logger import get_logger

logger = get_logger()


class PollingScheduler:
    """Runs a callback at a fixed interval in a background daemon thread."""

    def __init__(self, interval_seconds: int) -> None:
        self.interval_seconds = max(10, interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, callback: Callable[[], None]) -> None:
        """Start the polling loop in a daemon thread."""
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        self._stop_event.clear()

        def _run() -> None:
            logger.info("Polling scheduler started (interval=%ss)", self.interval_seconds)
            while not self._stop_event.is_set():
                try:
                    callback()
                except Exception:
                    logger.exception("Unhandled error in poll cycle")
                self._stop_event.wait(self.interval_seconds)
            logger.info("Polling scheduler stopped")

        self._thread = threading.Thread(target=_run, name="ema-poll", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the polling loop to stop and wait for thread exit."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def update_interval(self, interval_seconds: int) -> None:
        """Update polling interval for subsequent waits."""
        self.interval_seconds = max(10, interval_seconds)
