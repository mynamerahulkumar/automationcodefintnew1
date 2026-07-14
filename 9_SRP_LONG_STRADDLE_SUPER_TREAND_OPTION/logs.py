#!/usr/bin/env python3
"""Stream the latest dated log file like tail -f with simple colors."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
POLL_INTERVAL = 0.5

COLORS = {
    "ERROR": "\033[91m",
    "WARNING": "\033[93m",
    "INFO": "\033[92m",
    "DEBUG": "\033[94m",
    "RESET": "\033[0m",
}


def latest_log_file() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    dated = sorted(LOG_DIR.glob("????-??-??.log"))
    if dated:
        return dated[-1]
    from datetime import date

    return LOG_DIR / f"{date.today().isoformat()}.log"


def colorize(line: str) -> str:
    if not sys.stdout.isatty():
        return line
    for level, color in COLORS.items():
        if level == "RESET":
            continue
        if line.startswith(f"{level}:") or f":{level}:" in line:
            return f"{color}{line}{COLORS['RESET']}"
    return line


def tail_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()

    with open(path, encoding="utf-8") as handle:
        handle.seek(0, 2)
        while True:
            line = handle.readline()
            if line:
                print(colorize(line), end="")
            else:
                time.sleep(POLL_INTERVAL)


def main() -> None:
    log_file = latest_log_file()
    print(f"Streaming {log_file} (Ctrl+C to exit)")
    try:
        tail_file(log_file)
    except KeyboardInterrupt:
        print("\nStopped log viewer")
        sys.exit(0)


if __name__ == "__main__":
    main()
