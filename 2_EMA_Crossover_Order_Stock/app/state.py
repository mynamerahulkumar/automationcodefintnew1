"""Thread-safe in-memory bot state."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TradeRecord:
    """Last executed trade details."""

    order_id: str | None = None
    side: str | None = None
    price: float | None = None
    timestamp: str | None = None
    status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "side": self.side,
            "price": self.price,
            "timestamp": self.timestamp,
            "status": self.status,
        }


class BotState:
    """Shared mutable state for the trading bot and API status endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bot_status: str = "STOPPED"
        self.last_signal: str | None = None
        self.last_candle_time: str | None = None
        self.last_acted_signal: str | None = None
        self.last_acted_candle_time: str | None = None
        self.position_side: str = "FLAT"
        self.fast_ema: float | None = None
        self.slow_ema: float | None = None
        self.current_price: float | None = None
        self.last_trade: TradeRecord = TradeRecord()
        self.last_trade_at: datetime | None = None
        self.poll_count: int = 0
        self.last_poll_at: str | None = None
        self.last_error: str | None = None
        self.strategy_name: str = ""
        self.symbol: str = ""
        self.security_id: str = ""
        self.poll_interval: int = 30

    def update_poll(
        self,
        *,
        fast_ema: float | None,
        slow_ema: float | None,
        signal: str | None,
        candle_time: str | None,
        current_price: float | None = None,
    ) -> None:
        """Record latest poll metrics."""
        with self._lock:
            self.poll_count += 1
            self.last_poll_at = datetime.now(timezone.utc).isoformat()
            self.fast_ema = fast_ema
            self.slow_ema = slow_ema
            if current_price is not None:
                self.current_price = current_price
            if signal is not None:
                self.last_signal = signal
            if candle_time is not None:
                self.last_candle_time = candle_time

    def record_trade(
        self,
        *,
        order_id: str | None,
        side: str,
        price: float,
        status: str,
    ) -> None:
        """Record a completed or paper trade."""
        with self._lock:
            now = datetime.now(timezone.utc)
            self.last_trade = TradeRecord(
                order_id=order_id,
                side=side,
                price=price,
                timestamp=now.isoformat(),
                status=status,
            )
            self.last_trade_at = now
            if side == "BUY":
                self.position_side = "LONG"
            elif side == "SELL":
                self.position_side = "FLAT"

    def set_error(self, message: str) -> None:
        """Record the latest error."""
        with self._lock:
            self.last_error = message
            self.bot_status = "ERROR"

    def clear_error(self) -> None:
        """Clear error state when bot recovers."""
        with self._lock:
            self.last_error = None
            if self.bot_status == "ERROR":
                self.bot_status = "RUNNING"

    def set_running(self) -> None:
        with self._lock:
            self.bot_status = "RUNNING"

    def set_stopped(self) -> None:
        with self._lock:
            self.bot_status = "STOPPED"

    def should_skip_signal(self, signal: str, candle_time: str) -> bool:
        """Return True if this signal was already acted on for this candle."""
        with self._lock:
            return (
                signal == self.last_acted_signal
                and candle_time == self.last_acted_candle_time
            )

    def mark_signal_acted(self, signal: str, candle_time: str | None) -> None:
        """Record that a signal was acted upon for deduplication."""
        with self._lock:
            self.last_acted_signal = signal
            self.last_acted_candle_time = candle_time

    def in_cooldown(self, cooldown_seconds: int) -> bool:
        """Return True if still within post-trade cooldown."""
        with self._lock:
            if self.last_trade_at is None:
                return False
            elapsed = (datetime.now(timezone.utc) - self.last_trade_at).total_seconds()
            return elapsed < cooldown_seconds

    def should_skip_position(self, signal: str, one_position_only: bool) -> bool:
        """Return True if one_position_only blocks this signal."""
        if not one_position_only:
            return False
        with self._lock:
            if signal == "BUY" and self.position_side == "LONG":
                return True
            if signal == "SELL" and self.position_side == "FLAT":
                return True
        return False

    def snapshot(self) -> dict[str, Any]:
        """Return a thread-safe status snapshot."""
        with self._lock:
            return {
                "bot_status": self.bot_status,
                "strategy": self.strategy_name,
                "symbol": self.symbol,
                "security_id": self.security_id,
                "current_signal": self.last_signal,
                "fast_ema": self.fast_ema,
                "slow_ema": self.slow_ema,
                "current_price": self.current_price,
                "last_candle_time": self.last_candle_time,
                "position_side": self.position_side,
                "last_trade": self.last_trade.to_dict(),
                "poll_interval": self.poll_interval,
                "poll_count": self.poll_count,
                "last_poll_at": self.last_poll_at,
                "last_error": self.last_error,
            }


_bot_state: BotState | None = None


def get_bot_state() -> BotState:
    """Return the shared bot state singleton."""
    global _bot_state
    if _bot_state is None:
        _bot_state = BotState()
    return _bot_state
