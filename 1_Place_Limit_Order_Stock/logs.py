#!/usr/bin/env python3
"""Stream trading.log like tail -f."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_FILE = PROJECT_ROOT / "logs" / "trading.log"
POLL_INTERVAL = 0.5


def tail_file(path: Path) -> None:
    """Continuously print new lines from a log file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists():
        path.touch()

    with open(path, encoding="utf-8") as handle:
        handle.seek(0, 2)
        while True:
            line = handle.readline()
            if line:
                print(line, end="")
            else:
                time.sleep(POLL_INTERVAL)


def main() -> None:
    print(f"Streaming {LOG_FILE} (Ctrl+C to exit)")
    try:
        tail_file(LOG_FILE)
    except KeyboardInterrupt:
        print("\nStopped log viewer")
        sys.exit(0)


if __name__ == "__main__":
    main()
