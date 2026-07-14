"""Shared helpers for the Long Straddle ORB bot."""

from __future__ import annotations

from datetime import datetime, time

import pytz

IST = pytz.timezone("Asia/Kolkata")

INDEX_SECURITY_IDS = {
    "NIFTY": 13,
    "BANKNIFTY": 25,
    "FINNIFTY": 27,
    "MIDCPNIFTY": 442,
    "SENSEX": 51,
    "BANKEX": 50,
}

INDEX_STEP = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100,
    "BANKEX": 100,
}


def now_ist() -> datetime:
    """Return current datetime in Asia/Kolkata."""
    return datetime.now(IST)


def parse_hhmm(value: str) -> time:
    """Parse HH:MM or HH:MM:SS into a time object."""
    parts = str(value).strip().split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(parts[2]) if len(parts) > 2 else 0
    return time(hour=hour, minute=minute, second=second)


def _to_ist(now: datetime) -> datetime:
    if now.tzinfo is None:
        return IST.localize(now)
    return now.astimezone(IST)


def is_at_or_after(now: datetime, hhmm: str) -> bool:
    """Return True if now (IST-aware) is at or after HH:MM."""
    target = parse_hhmm(hhmm)
    current = _to_ist(now).time()
    return current >= target


def is_before(now: datetime, hhmm: str) -> bool:
    """Return True if now is strictly before HH:MM."""
    return not is_at_or_after(now, hhmm)


def format_money(value: float | None, digits: int = 2) -> str:
    """Format optional float for CLI display."""
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def safe_float(value: object, default: float | None = None) -> float | None:
    """Convert value to float when possible."""
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
