"""Thread-safe in-memory bot state and position tracking."""

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


@dataclass
class OrderRecord:
    """Record of an order placed today."""

    order_id: str
    leg: str
    side: str
    quantity: int
    price: float
    status: str
    symbol: str | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BotState:
    """Shared mutable state for the trading bot and API status endpoint."""

    PHASE_WAITING = "WAITING_ENTRY"
    PHASE_ENTERED = "ENTERED"
    PHASE_MONITORING_ST = "MONITORING_SUPERTREND"
    PHASE_CALL_ONLY = "CALL_ONLY"
    PHASE_PUT_ONLY = "PUT_ONLY"
    PHASE_FLAT = "FLAT"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bot_status: str = "STOPPED"
        self.phase: str = self.PHASE_WAITING
        self.strategy_name: str = "Long Straddle Supertrend Confirmation"
        self.underlying: str = ""
        self.expiry: str = ""
        self.atm_strike: float | None = None
        self.spot_price: float | None = None
        self.supertrend_value: float | None = None
        self.supertrend_direction: str = "NEUTRAL"
        self.supertrend_confirmed: bool = False
        self.remaining_leg: str | None = None
        self.exited_leg: str | None = None
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
        self.orders: list[OrderRecord] = []

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

    def add_order(self, record: OrderRecord) -> None:
        with self._lock:
            self.orders.append(record)

    def reset_session_if_needed(self, today: str) -> None:
        with self._lock:
            if self.session_date == today:
                return
            self.session_date = today
            self.phase = self.PHASE_WAITING
            self.entry_done = False
            self.supertrend_confirmed = False
            self.square_off_done = False
            self.supertrend_value = None
            self.supertrend_direction = "NEUTRAL"
            self.remaining_leg = None
            self.exited_leg = None
            self.call = LegState(side="CALL")
            self.put = LegState(side="PUT")
            self.combined_pnl = None
            self.atm_strike = None
            self.orders = []

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

    def positions_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "call": self.call.to_dict(),
                "put": self.put.to_dict(),
                "remaining_leg": self.remaining_leg,
                "exited_leg": self.exited_leg,
                "phase": self.phase,
            }

    def orders_list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [o.to_dict() for o in self.orders]

    def pnl_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "call_pnl": self.call.pnl,
                "put_pnl": self.put.pnl,
                "combined_pnl": self.combined_pnl,
            }

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
                "supertrend_value": self.supertrend_value,
                "supertrend_direction": self.supertrend_direction,
                "supertrend_confirmed": self.supertrend_confirmed,
                "remaining_leg": self.remaining_leg,
                "exited_leg": self.exited_leg,
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
                "orders_count": len(self.orders),
            }


_bot_state: BotState | None = None


def get_bot_state() -> BotState:
    global _bot_state
    if _bot_state is None:
        _bot_state = BotState()
    return _bot_state


# Alias for requirements naming
PositionManager = BotState


def get_position_manager() -> BotState:
    return get_bot_state()
