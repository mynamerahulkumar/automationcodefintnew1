"""PID-based process management for single-instance enforcement."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PID_FILE = PROJECT_ROOT / "logs" / "bot.pid"
WAIT_SECONDS = 10


def is_running(pid: int) -> bool:
    """Check whether a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def stop_process(pid: int, wait_seconds: int = WAIT_SECONDS) -> None:
    """Send SIGTERM, wait, then SIGKILL if needed."""
    if not is_running(pid):
        return

    os.kill(pid, signal.SIGTERM)
    for _ in range(wait_seconds * 2):
        if not is_running(pid):
            return
        time.sleep(0.5)

    os.kill(pid, signal.SIGKILL)
    time.sleep(0.5)


def read_pid(pid_file: Path = DEFAULT_PID_FILE) -> int | None:
    """Read PID from file, returning None if missing or invalid."""
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return None


def write_pid(pid: int, pid_file: Path = DEFAULT_PID_FILE) -> None:
    """Write PID to file."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid), encoding="utf-8")


def remove_pid(pid_file: Path = DEFAULT_PID_FILE) -> None:
    """Remove PID file if it exists."""
    pid_file.unlink(missing_ok=True)


def stop_bot(pid_file: Path = DEFAULT_PID_FILE) -> bool:
    """
    Stop the bot using the PID file.

    Returns True if a running process was stopped.
    """
    pid = read_pid(pid_file)
    if pid is None:
        return False

    was_running = is_running(pid)
    if was_running:
        stop_process(pid)
    remove_pid(pid_file)
    return was_running
