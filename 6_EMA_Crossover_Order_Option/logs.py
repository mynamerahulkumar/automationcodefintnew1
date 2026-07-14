#!/usr/bin/env python3
"""Stream trading.log like tail -f with formatted poll summaries."""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_FILE = PROJECT_ROOT / "logs" / "trading.log"
POLL_LOG_MARKER = "POLL SUMMARY |"
POLL_INTERVAL = 0.5


def _parse_poll_summary(line: str) -> dict[str, str] | None:
    """Parse key fields from a POLL SUMMARY log line."""
    if POLL_LOG_MARKER not in line:
        return None

    payload = line.split(POLL_LOG_MARKER, 1)[-1].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 7:
        return None

    symbol_segment = parts[0]
    symbol = symbol_segment.split("(")[0].strip()
    segment = "EQUITY"
    if "(" in symbol_segment and ")" in symbol_segment:
        segment = symbol_segment.split("(", 1)[1].rsplit(")", 1)[0].strip()

    def _value(part: str) -> str:
        return part.split(":", 1)[-1].strip() if ":" in part else part

    return {
        "symbol": symbol,
        "segment": segment,
        "ltp": _value(parts[1]),
        "fast_ema": parts[2],
        "slow_ema": parts[3],
        "trend": _value(parts[4]),
        "signal": _value(parts[5]),
        "candle": _value(parts[6]),
    }


def _print_poll_block(parsed: dict[str, str]) -> None:
    """Print a formatted poll summary block."""
    price_label = (
        "Option Price (LTP)"
        if parsed["segment"].upper() == "OPTION"
        else "Stock Price (LTP)"
    )
    print()
    print(f"  {parsed['symbol']} [{parsed['segment']}]")
    print(f"  {price_label:<22}: {parsed['ltp']}")
    for key in ("fast_ema", "slow_ema"):
        label, value = parsed[key].split(":", 1)
        print(f"  {label.strip():<22}: {value.strip()}")
    print(f"  {'Trend':<22}: {parsed['trend']}")
    print(f"  {'Signal':<22}: {parsed['signal']}")
    print(f"  {'Candle Time':<22}: {parsed['candle']}")
    print()


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
    print("Poll summaries show: LTP, Fast EMA, Slow EMA, Trend, Signal")
    try:
        tail_file(LOG_FILE)
    except KeyboardInterrupt:
        print("\nStopped log viewer")
        sys.exit(0)


if __name__ == "__main__":
    main()
