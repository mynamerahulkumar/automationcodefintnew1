"""NSE cash/F&O session helpers (Asia/Kolkata)."""

from __future__ import annotations

import re
from datetime import datetime, time

try:
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
except ImportError:  # Python < 3.9
    import pytz

    IST = pytz.timezone("Asia/Kolkata")

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: str) -> time:
    """Parse ``HH:MM`` into a ``datetime.time``."""
    text = str(value).strip()
    match = _HHMM.match(text)
    if not match:
        raise ValueError(f"Invalid time '{value}'; expected HH:MM")
    return time(int(match.group(1)), int(match.group(2)))


def ist_now(now: datetime | None = None) -> datetime:
    """Return ``now`` localized to IST (default: current clock)."""
    if now is None:
        return datetime.now(IST)
    if now.tzinfo is None:
        try:
            return IST.localize(now)  # pytz
        except AttributeError:
            return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def is_market_open(
    open_hhmm: str = "09:15",
    close_hhmm: str = "15:30",
    now: datetime | None = None,
) -> bool:
    """
    True during Mon–Fri when open <= clock < close in Asia/Kolkata.

    Close is exclusive so 15:30 exactly is outside the session.
    """
    current = ist_now(now)
    if current.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    open_t = parse_hhmm(open_hhmm)
    close_t = parse_hhmm(close_hhmm)
    clock = current.time().replace(second=0, microsecond=0)
    return open_t <= clock < close_t
