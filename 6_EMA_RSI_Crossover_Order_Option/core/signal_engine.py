"""Polling engine, position management, and CLI dashboard."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psutil
from colorama import Fore, Style, init as colorama_init

from core.config_loader import ConfigLoader, get_config_loader
from core.logger import get_logger
from core.market_data import get_market_data_service
from core.market_hours import is_market_open, session_status_message
from core.order_manager import OrderManagerError, get_order_manager
from core.strategy import Signal, generate_signal

logger = get_logger()
colorama_init(autoreset=True)


@dataclass
class Position:
    """Open position state."""

    side: str
    entry_price: float
    quantity: int
    entry_time: str


@dataclass
class EngineState:
    """Thread-safe shared state for API and polling."""

    running: bool = False
    strategy_mode: str = ""
    symbol: str = ""
    security_id: str = ""
    poll_interval: int = 30
    current_price: float | None = None
    candle_high: float | None = None
    candle_low: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    rsi: float | None = None
    signal: str = Signal.HOLD.value
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
        candle_high: float | None,
        candle_low: float | None,
        ema_fast: float | None,
        ema_slow: float | None,
        rsi: float | None,
        signal: str,
        candle_time: str | None,
    ) -> None:
        with self._lock:
            self.current_price = current_price
            self.candle_high = candle_high
            self.candle_low = candle_low
            self.ema_fast = ema_fast
            self.ema_slow = ema_slow
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
            self.trade_status = "Open"
            self.pnl_percent = 0.0

    def close_position(self) -> None:
        with self._lock:
            self.position = None
            self.pnl_percent = None
            self.trade_status = "Waiting"

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
            process = psutil.Process()
            return {
                "running": self.running,
                "strategy_mode": self.strategy_mode,
                "symbol": self.symbol,
                "security_id": self.security_id,
                "poll_interval": self.poll_interval,
                "current_price": self.current_price,
                "candle_high": self.candle_high,
                "candle_low": self.candle_low,
                "ema_fast": self.ema_fast,
                "ema_slow": self.ema_slow,
                "rsi": self.rsi,
                "signal": self.signal,
                "trade_status": self.trade_status,
                "position": position_data,
                "pnl_percent": self.pnl_percent,
                "last_error": self.last_error,
                "last_poll_time": self.last_poll_time,
                "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
                "cpu_percent": process.cpu_percent(interval=None),
            }


def _signal_color(signal: str) -> str:
    if signal == Signal.BUY.value:
        return Fore.GREEN
    if signal == Signal.SELL.value:
        return Fore.RED
    return Fore.YELLOW


def _format_metric(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def build_poll_summary_log(
    *,
    symbol: str,
    current_price: float | None,
    candle_high: float | None,
    candle_low: float | None,
    ema_fast: float | None,
    ema_slow: float | None,
    rsi: float | None,
    signal: str,
    trade_status: str,
    fast_period: int,
    slow_period: int,
    rsi_period: int,
) -> str:
    """Build a parseable poll summary line for logs.py."""
    return (
        f"POLL SUMMARY | {symbol} | "
        f"LTP: {_format_metric(current_price)} | "
        f"High: {_format_metric(candle_high)} | "
        f"Low: {_format_metric(candle_low)} | "
        f"EMA {fast_period}: {_format_metric(ema_fast)} | "
        f"EMA {slow_period}: {_format_metric(ema_slow)} | "
        f"RSI {rsi_period}: {_format_metric(rsi)} | "
        f"Signal: {signal} | "
        f"Trade: {trade_status}"
    )


def print_cli_dashboard(state: EngineState, config_loader: ConfigLoader) -> None:
    """Print colorized CLI dashboard after each poll cycle."""
    snap = state.snapshot()
    strategy = config_loader.get_strategy_config()
    ema = config_loader.get_ema_config()
    rsi = config_loader.get_rsi_config()
    risk = config_loader.get_risk_config()

    signal = snap["signal"]
    color = _signal_color(signal)
    position_text = "NONE"
    pnl_text = "N/A"
    if snap["position"]:
        position_text = f"{snap['position']['side']} @ {snap['position']['entry_price']:.2f}"
        if snap["pnl_percent"] is not None:
            pnl_text = f"{snap['pnl_percent']:.2f}%"

    print()
    print("-" * 55)
    print(f"Time          {snap['last_poll_time']}")
    print(f"Strategy      {strategy.get('mode')}")
    print(f"Symbol        {snap['symbol']}")
    price = snap["current_price"]
    print(f"LTP           {_format_metric(price)}")
    print(f"Candle High   {_format_metric(snap['candle_high'])}")
    print(f"Candle Low    {_format_metric(snap['candle_low'])}")
    if snap["ema_fast"] is not None:
        print(f"EMA {ema.get('fast')}       {_format_metric(snap['ema_fast'])}")
    if snap["ema_slow"] is not None:
        print(f"EMA {ema.get('slow')}      {_format_metric(snap['ema_slow'])}")
    if snap["rsi"] is not None:
        print(f"RSI {rsi.get('period')}         {_format_metric(snap['rsi'])}")
    print(f"Signal        {color}{signal}{Style.RESET_ALL}")
    print(f"Trade Status  {snap['trade_status']}")
    print(f"Position      {position_text}")
    print(f"PnL           {pnl_text}")
    print(f"Target        {risk.get('take_profit_percent')}%")
    print(f"SL            {risk.get('stop_loss_percent')}%")
    print(f"Polling       {snap['poll_interval']} sec")
    print(f"Memory        {snap['memory_mb']} MB")
    print(f"CPU           {snap['cpu_percent']}%")
    print("-" * 55)


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
                except MemoryError as exc:
                    logger.error(
                        "Unhandled error in poll cycle: MemoryError: %s "
                        "(1GB hosts: keep security_id in config; avoid loading CSV)",
                        exc,
                    )
                except Exception as exc:
                    logger.exception(
                        "Unhandled error in poll cycle: %s: %s",
                        type(exc).__name__,
                        exc,
                    )
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
        self._waiting_for_market_open = False

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
        logger.info("Signal engine stopped")

    def _sync_state_from_config(self) -> None:
        market = self.config_loader.get_market_config()
        strategy = self.config_loader.get_strategy_config()
        instrument = self.config_loader.get_resolved_instrument()

        self.state.strategy_mode = str(strategy.get("mode", "EMA"))
        self.state.symbol = str(market.get("trading_symbol", ""))
        self.state.security_id = str(instrument["security_id"])
        self.state.poll_interval = self.config_loader.get_polling_seconds()
        self.scheduler.update_interval(self.state.poll_interval)

    def _check_tp_sl(self, current_price: float) -> str | None:
        """Return exit signal if TP or SL is hit."""
        position = self.state.position
        if not position:
            return None

        risk = self.config_loader.get_risk_config()
        tp = float(risk.get("take_profit_percent", 1))
        sl = float(risk.get("stop_loss_percent", 0.5))
        entry = position.entry_price

        if position.side == "BUY":
            pnl = (current_price - entry) / entry * 100
            if pnl >= tp:
                return "SELL"
            if pnl <= -sl:
                return "SELL"
        elif position.side == "SELL":
            pnl = (entry - current_price) / entry * 100
            if pnl >= tp:
                return "BUY"
            if pnl <= -sl:
                return "BUY"
        return None

    def _execute_order(self, signal: str, current_price: float, reason: str) -> None:
        """Place order and update position state."""
        try:
            result = self.order_manager.place_signal_order(signal, current_price)
        except OrderManagerError as exc:
            logger.error("Order failed (%s): %s", reason, exc.message)
            self.state.set_error(exc.message)
            self.state.trade_status = "Error"
            return

        status = result.get("status", "")
        if status in {"success", "paper_trade"}:
            limit_price = float(result.get("limit_price", current_price))
            if signal in {Signal.BUY.value, Signal.SELL.value}:
                if self.state.position and signal != self.state.position.side:
                    self.state.close_position()
                else:
                    trading = self.config_loader.get_trading_config()
                    self.state.open_position(
                        side=signal,
                        entry_price=limit_price,
                        quantity=int(trading["quantity"]),
                    )
            self.state.trade_status = "Filled" if status == "success" else "Paper"
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
        try:
            self._poll_cycle_inner()
        except MemoryError as exc:
            self.state.set_error("MemoryError on low-RAM host")
            raise
        except Exception as exc:
            self.state.set_error(f"{type(exc).__name__}: {exc}")
            raise

    def _poll_cycle_inner(self) -> None:
        """Single polling iteration implementation."""
        hours = self.config_loader.get_market_hours_config()
        if hours["enabled"] and not is_market_open(hours["open"], hours["close"]):
            self.state.trade_status = "Waiting for market open"
            self.state.clear_error()
            if not self._waiting_for_market_open:
                logger.info(
                    "Outside market hours — %s Skipping trade lookup until session open.",
                    session_status_message(hours["open"], hours["close"]),
                )
                self._waiting_for_market_open = True
            return

        if hours["enabled"] and self._waiting_for_market_open:
            logger.info(
                "Market open (%s–%s IST) — resuming trade lookup",
                hours["open"],
                hours["close"],
            )
            self._waiting_for_market_open = False

        candles = self.market_data.fetch_candles()
        if candles is None:
            self.state.set_error("Failed to fetch candle data")
            logger.error(
                "Poll cycle skipped — failed to fetch candles "
                "(no LTP/EMA/RSI until Dhan data is available)"
            )
            return

        mode = self.config_loader.get_strategy_mode()
        result = generate_signal(
            mode,
            candles,
            self.config_loader.get_ema_config(),
            self.config_loader.get_rsi_config(),
        )

        current_price = self.market_data.fetch_ltp()
        if current_price is None and candles.last_close is not None:
            current_price = candles.last_close

        self.state.update_poll(
            current_price=current_price,
            candle_high=candles.last_high,
            candle_low=candles.last_low,
            ema_fast=result.ema_fast,
            ema_slow=result.ema_slow,
            rsi=result.rsi,
            signal=result.signal,
            candle_time=result.candle_time,
        )
        self.state.clear_error()

        ema_cfg = self.config_loader.get_ema_config()
        rsi_cfg = self.config_loader.get_rsi_config()
        log_line = build_poll_summary_log(
            symbol=self.state.symbol,
            current_price=current_price,
            candle_high=candles.last_high,
            candle_low=candles.last_low,
            ema_fast=result.ema_fast,
            ema_slow=result.ema_slow,
            rsi=result.rsi,
            signal=result.signal,
            trade_status=self.state.trade_status,
            fast_period=int(ema_cfg.get("fast", 9)),
            slow_period=int(ema_cfg.get("slow", 21)),
            rsi_period=int(rsi_cfg.get("period", 14)),
        )
        logger.info(log_line)
        print_cli_dashboard(self.state, self.config_loader)

        if current_price is None:
            return

        exit_signal = self._check_tp_sl(current_price)
        if exit_signal:
            self._execute_order(exit_signal, current_price, "TP/SL exit")
            return

        if result.signal == Signal.HOLD.value:
            return

        if self.state.position is not None:
            logger.info("Skipping %s — position already open", result.signal)
            return

        if self.state.should_skip_signal(result.signal, result.candle_time):
            logger.info("Skipping duplicate signal %s", result.signal)
            return

        self._execute_order(result.signal, current_price, "strategy signal")
        self.state.mark_signal_acted(result.signal, result.candle_time)


_signal_engine: SignalEngine | None = None


def get_signal_engine() -> SignalEngine:
    """Return the shared signal engine."""
    global _signal_engine
    if _signal_engine is None:
        _signal_engine = SignalEngine()
    return _signal_engine
