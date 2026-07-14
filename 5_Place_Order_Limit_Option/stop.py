#!/usr/bin/env python3
"""Gracefully stop the FastAPI server."""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PID_FILE = PROJECT_ROOT / "logs" / "server.pid"
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
        print(f"Process {pid} is not running")
        return

    print(f"Sending SIGTERM to PID {pid}")
    os.kill(pid, signal.SIGTERM)

    for _ in range(wait_seconds * 2):
        if not is_running(pid):
            print(f"Server stopped gracefully (PID {pid})")
            return
        time.sleep(0.5)

    print(f"Process {pid} did not stop in time, sending SIGKILL")
    os.kill(pid, signal.SIGKILL)
    time.sleep(0.5)
    print(f"Server force-stopped (PID {pid})")


def stop_server(pid_file: Path = PID_FILE) -> bool:
    """
    Stop the server using the PID file.

    Returns True if a running process was stopped.
    """
    if not pid_file.exists():
        return False

    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        pid_file.unlink(missing_ok=True)
        return False

    was_running = is_running(pid)
    if was_running:
        stop_process(pid)
    pid_file.unlink(missing_ok=True)
    return was_running


def main() -> None:
    if not stop_server():
        print(f"No running server found ({PID_FILE})")
        sys.exit(1)


if __name__ == "__main__":
    main()
