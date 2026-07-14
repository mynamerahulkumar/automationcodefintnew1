"""Thread-safe in-memory bot state for dual-leg Long Straddle EMA."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class LegState:
    """Tracks one option leg (CALL or PUT)."""

    side: str
    status: str = "FLAT"
    order_id: str | None = None
    security_id: str | None = None
    trading_symbol: str | None = None
    custom_symbol: str | None = None
    strike: float | None = None
    quantity: int = 0
    entry_price: float | None = None
    current_price: float | None = None
    pnl: float | None = None
    stop_loss: float | None = None
    target: float | None = None
    trailing_stop: float | None = None
    peak_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandleSnapshot:
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BotState:
    """Shared mutable state for the trading bot and API status endpoint."""

    PHASE_WAITING = "WAITING_ENTRY"
    PHASE_ENTERED = "ENTERED"
    PHASE_MONITORING_EMA = "MONITORING_EMA"
    PHASE_CALL_ONLY = "CALL_ONLY"
    PHASE_PUT_ONLY = "PUT_ONLY"
    PHASE_FLAT = "FLAT"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bot_status: str = "STOPPED"
        self.phase: str = self.PHASE_WAITING
        self.strategy_name: str = "Long Straddle EMA Confirmation"
        self.underlying: str = ""
        self.expiry: str = ""
        self.atm_strike: float | None = None
        self.spot_price: float | None = None
        self.fast_ema: float | None = None
        self.slow_ema: float | None = None
        self.ema_trend: str = "NEUTRAL"
        self.ema_confirmed: bool = False
        self.remaining_leg: str | None = None
        self.call = LegState(side="CALL")
        self.put = LegState(side="PUT")
        self.combined_pnl: float | None = None
        self.candle = CandleSnapshot()
        self.poll_count: int = 0
        self.last_poll_at: str | None = None
        self.last_error: str | None = None
        self.poll_interval: int = 30
        self.api_response_ms: float | None = None
        self.next_poll_at: str | None = None
        self.entry_done: bool = False
        self.session_date: str | None = None
        self.square_off_done: bool = False
        self.manual_stop_requested: bool = False
        self.memory_mb: float | None = None
        self.cpu_percent: float | None = None

    def set_running(self) -> None:
        with self._lock:
            self.bot_status = "RUNNING"

    def set_stopped(self) -> None:
        with self._lock:
            self.bot_status = "STOPPED"

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def clear_error(self) -> None:
        with self._lock:
            self.last_error = None

    def reset_session_if_needed(self, today: str) -> None:
        with self._lock:
            if self.session_date == today:
                return
            self.session_date = today
            self.phase = self.PHASE_WAITING
            self.entry_done = False
            self.ema_confirmed = False
            self.square_off_done = False
            self.fast_ema = None
            self.slow_ema = None
            self.ema_trend = "NEUTRAL"
            self.remaining_leg = None
            self.call = LegState(side="CALL")
            self.put = LegState(side="PUT")
            self.combined_pnl = None
            self.atm_strike = None

    def update_poll_meta(
        self,
        *,
        api_response_ms: float | None = None,
        next_poll_at: str | None = None,
        memory_mb: float | None = None,
        cpu_percent: float | None = None,
    ) -> None:
        with self._lock:
            self.poll_count += 1
            self.last_poll_at = datetime.now(timezone.utc).isoformat()
            if api_response_ms is not None:
                self.api_response_ms = api_response_ms
            if next_poll_at is not None:
                self.next_poll_at = next_poll_at
            if memory_mb is not None:
                self.memory_mb = memory_mb
            if cpu_percent is not None:
                self.cpu_percent = cpu_percent

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "bot_status": self.bot_status,
                "phase": self.phase,
                "strategy_name": self.strategy_name,
                "underlying": self.underlying,
                "expiry": self.expiry,
                "atm_strike": self.atm_strike,
                "spot_price": self.spot_price,
                "fast_ema": self.fast_ema,
                "slow_ema": self.slow_ema,
                "ema_trend": self.ema_trend,
                "ema_confirmed": self.ema_confirmed,
                "remaining_leg": self.remaining_leg,
                "call": self.call.to_dict(),
                "put": self.put.to_dict(),
                "combined_pnl": self.combined_pnl,
                "candle": self.candle.to_dict(),
                "poll_count": self.poll_count,
                "last_poll_at": self.last_poll_at,
                "last_error": self.last_error,
                "poll_interval": self.poll_interval,
                "api_response_ms": self.api_response_ms,
                "next_poll_at": self.next_poll_at,
                "entry_done": self.entry_done,
                "memory_mb": self.memory_mb,
                "cpu_percent": self.cpu_percent,
            }


_bot_state: BotState | None = None


def get_bot_state() -> BotState:
    global _bot_state
    if _bot_state is None:
        _bot_state = BotState()
    return _bot_state
