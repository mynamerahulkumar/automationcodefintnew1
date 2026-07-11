"""Polling engine, position management, and CLI dashboard."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from colorama import Fore, Style, init as colorama_init

from core.config_loader import ConfigLoader, get_config_loader
from core.logger import flush_logger, get_logger
from core.market_data import get_market_data_service
from core.order_manager import OrderManagerError, get_order_manager
from core.strategy import Signal, generate_signal

logger = get_logger()
colorama_init(autoreset=True)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_STATUS_FILE = PROJECT_ROOT / "logs" / "runtime_status.json"


@dataclass
class Position:
    """Open position state."""

    side: str
    entry_price: float
    quantity: int
    entry_time: str


@dataclass
class PollSnapshot:
    """Single poll cycle display data."""

    poll_number: int
    time_str: str
    price: float | None
    macd: float | None
    signal_line: float | None
    histogram: float | None
    rsi: float | None
    signal: str
    trade_status: str
    position_text: str
    pnl_text: str


@dataclass
class EngineState:
    """Thread-safe shared state for API and polling."""

    running: bool = False
    strategy_mode: str = ""
    symbol: str = ""
    security_id: str = ""
    poll_interval: int = 30
    poll_number: int = 0
    current_price: float | None = None
    macd: float | None = None
    signal_line: float | None = None
    histogram: float | None = None
    rsi: float | None = None
    signal: str = Signal.NO_SIGNAL.value
    trade_status: str = "Waiting"
    position: Position | None = None
    pnl_percent: float | None = None
    last_error: str | None = None
    last_poll_time: str | None = None
    last_candle_time: str | None = None
    _last_acted_signal: tuple[str, str] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update_poll(
        self,
        *,
        current_price: float | None,
        macd: float | None,
        signal_line: float | None,
        histogram: float | None,
        rsi: float | None,
        signal: str,
        candle_time: str | None,
    ) -> None:
        with self._lock:
            self.poll_number += 1
            self.current_price = current_price
            self.macd = macd
            self.signal_line = signal_line
            self.histogram = histogram
            self.rsi = rsi
            self.signal = signal
            self.last_candle_time = candle_time
            self.last_poll_time = datetime.now().strftime("%H:%M:%S")
            if self.position and current_price and self.position.entry_price:
                if self.position.side == "BUY":
                    self.pnl_percent = (
                        (current_price - self.position.entry_price)
                        / self.position.entry_price
                        * 100
                    )
                else:
                    self.pnl_percent = (
                        (self.position.entry_price - current_price)
                        / self.position.entry_price
                        * 100
                    )

    def open_position(self, side: str, entry_price: float, quantity: int) -> None:
        with self._lock:
            self.position = Position(
                side=side,
                entry_price=entry_price,
                quantity=quantity,
                entry_time=datetime.now().isoformat(),
            )
            self.pnl_percent = 0.0

    def close_position(self) -> None:
        with self._lock:
            self.position = None
            self.pnl_percent = None
            self.trade_status = "Waiting"

    def set_trade_status(self, status: str) -> None:
        with self._lock:
            self.trade_status = status

    def set_signal(self, signal: str) -> None:
        with self._lock:
            self.signal = signal

    def should_skip_signal(self, signal: str, candle_time: str | None) -> bool:
        with self._lock:
            if not candle_time:
                return False
            key = (signal, candle_time)
            if self._last_acted_signal == key:
                return True
            return False

    def mark_signal_acted(self, signal: str, candle_time: str | None) -> None:
        with self._lock:
            if candle_time:
                self._last_acted_signal = (signal, candle_time)

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def clear_error(self) -> None:
        with self._lock:
            self.last_error = None

    def _position_display_unlocked(self) -> str:
        if self.position and self.position.side == "BUY":
            return "LONG"
        if self.position and self.position.side == "SELL":
            return "SHORT"
        return "None"

    def _pnl_display_unlocked(self) -> str:
        if self.pnl_percent is None:
            return "0.00"
        sign = "+" if self.pnl_percent >= 0 else ""
        return f"{sign}{self.pnl_percent:.2f}"

    def position_display(self) -> str:
        with self._lock:
            return self._position_display_unlocked()

    def pnl_display(self) -> str:
        with self._lock:
            return self._pnl_display_unlocked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            position_data = None
            if self.position:
                position_data = {
                    "side": self.position.side,
                    "entry_price": self.position.entry_price,
                    "quantity": self.position.quantity,
                    "entry_time": self.position.entry_time,
                }
            return {
                "running": self.running,
                "strategy_mode": self.strategy_mode,
                "symbol": self.symbol,
                "security_id": self.security_id,
                "poll_interval": self.poll_interval,
                "poll_number": self.poll_number,
                "current_price": self.current_price,
                "macd": self.macd,
                "signal_line": self.signal_line,
                "histogram": self.histogram,
                "rsi": self.rsi,
                "signal": self.signal,
                "trade_status": self.trade_status,
                "position": position_data,
                "position_display": self._position_display_unlocked(),
                "pnl_percent": self.pnl_percent,
                "pnl_display": self._pnl_display_unlocked(),
                "last_error": self.last_error,
                "last_poll_time": self.last_poll_time,
            }


def _signal_color(signal: str) -> str:
    signal = signal.upper()
    if signal == Signal.BUY.value:
        return Fore.GREEN
    if signal == Signal.SELL.value:
        return Fore.RED
    if signal == Signal.EXIT.value:
        return Fore.MAGENTA
    return Fore.YELLOW


def _format_metric(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def build_poll_summary_log(
    *,
    symbol: str,
    current_price: float | None,
    macd: float | None,
    signal_line: float | None,
    histogram: float | None,
    rsi: float | None,
    signal: str,
    trade_status: str,
    position_text: str,
    pnl_text: str,
) -> str:
    """Build a parseable poll summary line for logs.py."""
    return (
        f"POLL SUMMARY | {symbol} | "
        f"Price: {_format_metric(current_price)} | "
        f"MACD: {_format_metric(macd)} | "
        f"Signal: {_format_metric(signal_line)} | "
        f"Histogram: {_format_metric(histogram)} | "
        f"RSI: {_format_metric(rsi)} | "
        f"Signal: {signal} | "
        f"Trade: {trade_status} | "
        f"Position: {position_text} | "
        f"PnL: {pnl_text}"
    )


def _build_poll_block(snapshot: PollSnapshot) -> str:
    """Build a single poll block as plain text (no colors)."""
    lines = [
        "=" * 74,
        "",
        f"POLL #{snapshot.poll_number}",
        "",
        f"Time            : {snapshot.time_str}",
        "",
        f"Price           : {_format_metric(snapshot.price)}",
        "",
        f"MACD            : {_format_metric(snapshot.macd)}",
        "",
        f"Signal          : {_format_metric(snapshot.signal_line)}",
        "",
        f"Histogram       : {_format_metric(snapshot.histogram)}",
        "",
        f"RSI             : {_format_metric(snapshot.rsi)}",
        "",
        f"Signal          : {snapshot.signal}",
        "",
        f"Trade           : {snapshot.trade_status}",
        "",
        f"Position        : {snapshot.position_text}",
        "",
        f"PnL             : {snapshot.pnl_text}",
        "",
        "=" * 74,
    ]
    return "\n".join(lines)


def _build_colored_poll_block(snapshot: PollSnapshot) -> str:
    """Build a single poll block with colorized signal line."""
    color = _signal_color(snapshot.signal)
    lines = [
        "=" * 74,
        "",
        f"POLL #{snapshot.poll_number}",
        "",
        f"Time            : {snapshot.time_str}",
        "",
        f"Price           : {_format_metric(snapshot.price)}",
        "",
        f"MACD            : {_format_metric(snapshot.macd)}",
        "",
        f"Signal          : {_format_metric(snapshot.signal_line)}",
        "",
        f"Histogram       : {_format_metric(snapshot.histogram)}",
        "",
        f"RSI             : {_format_metric(snapshot.rsi)}",
        "",
        f"Signal          : {color}{snapshot.signal}{Style.RESET_ALL}",
        "",
        f"Trade           : {snapshot.trade_status}",
        "",
        f"Position        : {snapshot.position_text}",
        "",
        f"PnL             : {snapshot.pnl_text}",
        "",
        "=" * 74,
    ]
    return "\n".join(lines)


class RollingDashboard:
    """Maintains and renders the last N poll blocks."""

    def __init__(self, max_visible: int = 3) -> None:
        self.max_visible = max(1, max_visible)
        self._polls: deque[PollSnapshot] = deque(maxlen=self.max_visible)
        self._lines_per_block = 25

    def update_max_visible(self, max_visible: int) -> None:
        self.max_visible = max(1, max_visible)
        polls = list(self._polls)
        self._polls = deque(polls[-self.max_visible :], maxlen=self.max_visible)

    def add_poll(self, snapshot: PollSnapshot) -> None:
        self._polls.append(snapshot)

    def render(self) -> None:
        """Re-render the rolling dashboard to stdout."""
        if not sys.stdout.isatty():
            return

        if os.environ.get("LOG_CONSOLE", "").lower() not in {"1", "true", "yes"}:
            return

        total_lines = self.max_visible * self._lines_per_block + 2
        sys.stdout.write(f"\033[{total_lines}A\033[J")
        sys.stdout.flush()

        for snapshot in self._polls:
            print(_build_colored_poll_block(snapshot))
            print()


_dashboard: RollingDashboard | None = None


def get_dashboard(max_visible: int = 3) -> RollingDashboard:
    """Return the shared rolling dashboard."""
    global _dashboard
    if _dashboard is None:
        _dashboard = RollingDashboard(max_visible)
    return _dashboard


def save_runtime_status(state: EngineState) -> None:
    """Persist last runtime status to disk."""
    snap = state.snapshot()
    payload = {
        "poll_number": snap["poll_number"],
        "last_price": snap["current_price"],
        "macd": snap["macd"],
        "signal_line": snap["signal_line"],
        "histogram": snap["histogram"],
        "rsi": snap["rsi"],
        "signal": snap["signal"],
        "position": snap["position_display"],
        "trade_status": snap["trade_status"],
        "stopped_at": datetime.now().isoformat(),
    }
    RUNTIME_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Runtime status saved to %s", RUNTIME_STATUS_FILE.name)


class PollingScheduler:
    """Runs poll callback at fixed interval in a daemon thread."""

    def __init__(self, interval_seconds: int) -> None:
        self.interval_seconds = max(10, interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, callback) -> None:
        if self.is_running:
            return
        self._stop_event.clear()

        def _run() -> None:
            logger.info("Polling started (interval=%ss)", self.interval_seconds)
            while not self._stop_event.is_set():
                try:
                    callback()
                except Exception:
                    logger.exception("Unhandled error in poll cycle")
                self._stop_event.wait(self.interval_seconds)
            logger.info("Polling stopped")

        self._thread = threading.Thread(target=_run, name="signal-poll", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def update_interval(self, interval_seconds: int) -> None:
        self.interval_seconds = max(10, interval_seconds)


class SignalEngine:
    """Coordinates polling, strategy evaluation, orders, and position management."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.state = EngineState()
        self.market_data = get_market_data_service()
        self.order_manager = get_order_manager()
        self.scheduler = PollingScheduler(self.config_loader.get_polling_seconds())
        self.dashboard = get_dashboard(self.config_loader.get_max_visible_polls())

    def start(self) -> None:
        """Start the polling engine."""
        self._sync_state_from_config()
        self.state.running = True
        self.scheduler.start(self.poll_cycle)
        logger.info("Signal engine started")

    def stop(self) -> None:
        """Stop the polling engine."""
        self.scheduler.stop()
        self.state.running = False
        save_runtime_status(self.state)
        flush_logger()
        logger.info("Signal engine stopped")

    def _sync_state_from_config(self) -> None:
        market = self.config_loader.get_market_config()
        strategy = self.config_loader.get_strategy_config()
        instrument = self.config_loader.get_resolved_instrument()

        self.state.strategy_mode = str(strategy.get("mode", "MACD_RSI"))
        self.state.symbol = str(market.get("trading_symbol", ""))
        self.state.security_id = str(instrument["security_id"])
        self.state.poll_interval = self.config_loader.get_polling_seconds()
        self.scheduler.update_interval(self.state.poll_interval)
        max_visible = self.config_loader.get_max_visible_polls()
        self.dashboard.update_max_visible(max_visible)

    def _check_tp_sl(self, current_price: float) -> str | None:
        """Return exit side if TP or SL is hit."""
        position = self.state.position
        if not position:
            return None

        risk = self.config_loader.get_risk_config()
        tp = float(risk.get("take_profit_percent", 1))
        sl = float(risk.get("stop_loss_percent", 0.5))
        entry = position.entry_price

        if position.side == "BUY":
            pnl = (current_price - entry) / entry * 100
            if pnl >= tp or pnl <= -sl:
                return "SELL"
        elif position.side == "SELL":
            pnl = (entry - current_price) / entry * 100
            if pnl >= tp or pnl <= -sl:
                return "BUY"
        return None

    def _trade_status_for_order(self, signal: str, is_exit: bool = False) -> str:
        if is_exit:
            return "EXIT ORDER PLACED"
        if signal == Signal.BUY.value:
            return "BUY ORDER PLACED"
        if signal == Signal.SELL.value:
            return "SELL ORDER PLACED"
        return "Waiting"

    def _execute_order(
        self,
        signal: str,
        current_price: float,
        reason: str,
        *,
        is_exit: bool = False,
    ) -> None:
        """Place order and update position state."""
        try:
            result = self.order_manager.place_signal_order(signal, current_price)
        except OrderManagerError as exc:
            logger.error("Order failed (%s): %s", reason, exc.message)
            self.state.set_error(exc.message)
            self.state.set_trade_status("Error")
            return

        status = result.get("status", "")
        if status in {"success", "paper_trade"}:
            limit_price = float(result.get("limit_price", current_price))
            if is_exit:
                self.state.set_signal(Signal.EXIT.value)
                self.state.set_trade_status(self._trade_status_for_order(signal, is_exit=True))
                self.state.close_position()
            elif signal in {Signal.BUY.value, Signal.SELL.value}:
                if self.state.position and signal != self.state.position.side:
                    self.state.close_position()
                else:
                    trading = self.config_loader.get_trading_config()
                    self.state.open_position(
                        side=signal,
                        entry_price=limit_price,
                        quantity=int(trading["quantity"]),
                    )
                self.state.set_trade_status(self._trade_status_for_order(signal))
            logger.info(
                "Order executed (%s): %s @ %s status=%s",
                reason,
                signal,
                limit_price,
                status,
            )
        self.state.clear_error()

    def poll_cycle(self) -> None:
        """Single polling iteration."""
        candles = self.market_data.fetch_candles()
        if candles is None:
            self.state.set_error("Failed to fetch candle data")
            return

        mode = self.config_loader.get_strategy_mode()
        result = generate_signal(
            mode,
            candles,
            self.config_loader.get_macd_config(),
            self.config_loader.get_rsi_config(),
        )

        current_price = self.market_data.fetch_ltp()
        if current_price is None and candles.last_close is not None:
            current_price = candles.last_close

        self.state.update_poll(
            current_price=current_price,
            macd=result.macd,
            signal_line=result.signal_line,
            histogram=result.histogram,
            rsi=result.rsi,
            signal=result.signal,
            candle_time=result.candle_time,
        )
        self.state.clear_error()

        snap = self.state.snapshot()
        log_line = build_poll_summary_log(
            symbol=self.state.symbol,
            current_price=current_price,
            macd=result.macd,
            signal_line=result.signal_line,
            histogram=result.histogram,
            rsi=result.rsi,
            signal=result.signal,
            trade_status=snap["trade_status"],
            position_text=snap["position_display"],
            pnl_text=snap["pnl_display"],
        )
        logger.info(log_line)

        poll_snapshot = PollSnapshot(
            poll_number=snap["poll_number"],
            time_str=snap["last_poll_time"] or "",
            price=current_price,
            macd=result.macd,
            signal_line=result.signal_line,
            histogram=result.histogram,
            rsi=result.rsi,
            signal=result.signal,
            trade_status=snap["trade_status"],
            position_text=snap["position_display"],
            pnl_text=snap["pnl_display"],
        )
        self.dashboard.add_poll(poll_snapshot)
        self.dashboard.render()

        if current_price is None:
            return

        exit_signal = self._check_tp_sl(current_price)
        if exit_signal:
            self._execute_order(exit_signal, current_price, "TP/SL exit", is_exit=True)
            self._refresh_dashboard_after_trade(result, current_price)
            return

        if result.signal == Signal.NO_SIGNAL.value:
            return

        if self.state.position is not None:
            logger.info("Skipping %s — position already open", result.signal)
            return

        if self.state.should_skip_signal(result.signal, result.candle_time):
            logger.info("Skipping duplicate signal %s", result.signal)
            return

        self._execute_order(result.signal, current_price, "strategy signal")
        self._refresh_dashboard_after_trade(result, current_price)
        self.state.mark_signal_acted(result.signal, result.candle_time)

    def _refresh_dashboard_after_trade(
        self,
        result: Any,
        current_price: float | None,
    ) -> None:
        """Update dashboard after order execution."""
        snap = self.state.snapshot()
        poll_snapshot = PollSnapshot(
            poll_number=snap["poll_number"],
            time_str=snap["last_poll_time"] or "",
            price=current_price,
            macd=result.macd,
            signal_line=result.signal_line,
            histogram=result.histogram,
            rsi=result.rsi,
            signal=snap["signal"],
            trade_status=snap["trade_status"],
            position_text=snap["position_display"],
            pnl_text=snap["pnl_display"],
        )
        if self.dashboard._polls:
            self.dashboard._polls[-1] = poll_snapshot
        self.dashboard.render()


_signal_engine: SignalEngine | None = None


def get_signal_engine() -> SignalEngine:
    """Return the shared signal engine."""
    global _signal_engine
    if _signal_engine is None:
        _signal_engine = SignalEngine()
    return _signal_engine
