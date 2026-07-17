#!/usr/bin/env python3
"""Stream trading.log like tail -f with formatted poll summaries."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from colorama import Fore, Style, init as colorama_init

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_FILE = PROJECT_ROOT / "logs" / "trading.log"
POLL_LOG_MARKER = "POLL SUMMARY |"
POLL_INTERVAL = 0.5

colorama_init(autoreset=True)


def _signal_color(signal: str) -> str:
    signal = signal.upper()
    if signal == "BUY":
        return Fore.GREEN
    if signal == "SELL":
        return Fore.RED
    return Fore.YELLOW


def _parse_poll_summary(line: str) -> dict[str, str] | None:
    """Parse key fields from a POLL SUMMARY log line."""
    if POLL_LOG_MARKER not in line:
        return None

    payload = line.split(POLL_LOG_MARKER, 1)[-1].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 9:
        return None

    def _value(part: str) -> str:
        return part.split(":", 1)[-1].strip() if ":" in part else part

    return {
        "symbol": parts[0],
        "ltp": _value(parts[1]),
        "high": _value(parts[2]),
        "low": _value(parts[3]),
        "ema_fast": parts[4],
        "ema_slow": parts[5],
        "rsi": parts[6],
        "signal": _value(parts[7]),
        "trade": _value(parts[8]),
    }


def _print_poll_block(parsed: dict[str, str]) -> None:
    """Print a formatted poll summary block."""
    signal = parsed["signal"]
    color = _signal_color(signal)
    print()
    print("-" * 55)
    print(f"Symbol        {parsed['symbol']}")
    print(f"LTP           {parsed['ltp']}")
    print(f"Candle High   {parsed['high']}")
    print(f"Candle Low    {parsed['low']}")
    print(f"{parsed['ema_fast']}")
    print(f"{parsed['ema_slow']}")
    print(f"{parsed['rsi']}")
    print(f"Signal        {color}{signal}{Style.RESET_ALL}")
    print(f"Trade         {parsed['trade']}")
    print("-" * 55)


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
                parsed = _parse_poll_summary(line)
                if parsed:
                    _print_poll_block(parsed)
                elif POLL_LOG_MARKER not in line:
                    print(line, end="")
            else:
                time.sleep(POLL_INTERVAL)


def main() -> None:
    print(f"Streaming {LOG_FILE} (Ctrl+C to exit)")
    print("Poll summaries: LTP, High, Low, EMA, RSI, Signal (BUY=green, SELL=red, HOLD=yellow)")
    try:
        tail_file(LOG_FILE)
    except KeyboardInterrupt:
        print("\nStopped log viewer")
        sys.exit(0)


if __name__ == "__main__":
    main()
