#!/usr/bin/env python3
"""Stop the SRP Dhan Trading Bot safely."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PID_FILE = PROJECT_ROOT / "logs" / "bot.pid"


def main() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))
    from core.process_manager import stop_bot

    if stop_bot(PID_FILE):
        print("Bot stopped successfully.")
    else:
        print("No running bot found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
