"""MACD, RSI, and combined MACD+RSI strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from core.market_data import CandleData


class StrategyMode(str, Enum):
    """Supported strategy modes."""

    MACD = "MACD"
    RSI = "RSI"
    MACD_RSI = "MACD_RSI"


class Signal(str, Enum):
    """Trading signal values."""

    BUY = "BUY"
    SELL = "SELL"
    NO_SIGNAL = "NO SIGNAL"
    EXIT = "EXIT"


@dataclass
class SignalResult:
    """Strategy evaluation output."""

    signal: str
    price: float | None
    macd: float | None
    signal_line: float | None
    histogram: float | None
    rsi: float | None
    macd_prev: float | None = None
    signal_line_prev: float | None = None
    rsi_prev: float | None = None
    candle_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "price": self.price,
            "macd": self.macd,
            "signal_line": self.signal_line,
            "histogram": self.histogram,
            "rsi": self.rsi,
            "candle_time": self.candle_time,
        }


def compute_ema_series(closes: list[float], period: int) -> list[float]:
    """
    Compute EMA series using TradingView-style SMA seed.

    First ``period`` closes form an SMA seed; subsequent values use the
    standard EMA formula. Early bars before the seed are left as NaN so
    the series stays aligned with ``closes``.
    """
    if not closes or period <= 0 or len(closes) < period:
        return []

    k = 2.0 / (period + 1)
    ema_values: list[float] = [float("nan")] * (period - 1)

    ema = sum(closes[:period]) / float(period)
    ema_values.append(ema)

    for price in closes[period:]:
        ema = float(price) * k + ema * (1.0 - k)
        ema_values.append(ema)

    return ema_values


def compute_rsi_series(closes: list[float], period: int) -> list[float]:
    """Compute RSI series using Wilder's smoothing."""
    if len(closes) < period + 1:
        return []

    prices = np.array(closes, dtype=float)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    rsi_values: list[float] = [50.0] * period

    if avg_loss == 0:
        rsi_values.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

    for i in range(period, len(deltas)):
        gain = float(gains[i])
        loss = float(losses[i])
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

    return rsi_values


def compute_macd_series(
    closes: list[float],
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> tuple[list[float], list[float], list[float]]:
    """
    Compute MACD line, signal line, and histogram series.

    MACD line = EMA(fast) - EMA(slow)
    Signal line = EMA(MACD, signal_period)
    Histogram = MACD - Signal

    Leading NaNs from SMA-seeded EMAs are stripped before the signal EMA
    so the series stays TradingView-aligned.
    """
    if len(closes) < slow_period + signal_period:
        return [], [], []

    fast_ema = compute_ema_series(closes, fast_period)
    slow_ema = compute_ema_series(closes, slow_period)
    if not fast_ema or not slow_ema:
        return [], [], []

    macd_line: list[float] = []
    for fast_val, slow_val in zip(fast_ema, slow_ema):
        if fast_val != fast_val or slow_val != slow_val:  # NaN
            macd_line.append(float("nan"))
        else:
            macd_line.append(fast_val - slow_val)

    valid_macd = [v for v in macd_line if v == v]
    if len(valid_macd) < signal_period:
        return [], [], []

    signal_valid = compute_ema_series(valid_macd, signal_period)
    if not signal_valid:
        return [], [], []

    # Align signal back onto full-length series (NaN until MACD is valid + seeded).
    signal_line: list[float] = [float("nan")] * len(macd_line)
    valid_indices = [i for i, v in enumerate(macd_line) if v == v]
    for idx, sig in zip(valid_indices, signal_valid):
        signal_line[idx] = sig

    histogram: list[float] = []
    for macd_val, sig_val in zip(macd_line, signal_line):
        if macd_val != macd_val or sig_val != sig_val:
            histogram.append(float("nan"))
        else:
            histogram.append(macd_val - sig_val)

    return macd_line, signal_line, histogram


def _empty_result(candles: CandleData) -> SignalResult:
    return SignalResult(
        signal=Signal.NO_SIGNAL.value,
        price=candles.last_close,
        macd=None,
        signal_line=None,
        histogram=None,
        rsi=None,
        candle_time=candles.last_timestamp,
    )


def _macd_crossover_signal(
    macd_prev: float,
    macd_curr: float,
    signal_prev: float,
    signal_curr: float,
) -> str:
    """MACD only: crossover on last two completed values."""
    if macd_prev <= signal_prev and macd_curr > signal_curr:
        return Signal.BUY.value
    if macd_prev >= signal_prev and macd_curr < signal_curr:
        return Signal.SELL.value
    return Signal.NO_SIGNAL.value


def _rsi_crossover_signal(
    rsi_prev: float,
    rsi_curr: float,
    buy_level: float,
    sell_level: float,
) -> str:
    """RSI only: cross above buy level or cross below sell level."""
    if rsi_prev <= buy_level and rsi_curr > buy_level:
        return Signal.BUY.value
    if rsi_prev >= sell_level and rsi_curr < sell_level:
        return Signal.SELL.value
    return Signal.NO_SIGNAL.value


def _macd_rsi_combined_signal(
    macd_curr: float,
    signal_curr: float,
    rsi_curr: float,
    buy_level: float,
    sell_level: float,
) -> str:
    """MACD+RSI: both indicators must agree (level-based)."""
    if macd_curr > signal_curr and rsi_curr > buy_level:
        return Signal.BUY.value
    if macd_curr < signal_curr and rsi_curr < sell_level:
        return Signal.SELL.value
    return Signal.NO_SIGNAL.value


def generate_signal(
    mode: str,
    candles: CandleData,
    macd_config: dict[str, Any],
    rsi_config: dict[str, Any],
) -> SignalResult:
    """
    Evaluate the active strategy and return BUY, SELL, or NO SIGNAL.

    The trading engine calls this without knowing which strategy is active.
    """
    mode_upper = str(mode).upper()
    closes = candles.closes

    fast_period = int(macd_config.get("fast", 12))
    slow_period = int(macd_config.get("slow", 26))
    signal_period = int(macd_config.get("signal", 9))
    rsi_period = int(rsi_config.get("period", 14))
    buy_level = float(rsi_config.get("buy", 60))
    sell_level = float(rsi_config.get("sell", 40))

    min_bars = max(
        slow_period + signal_period + 2 if mode_upper in {StrategyMode.MACD.value, StrategyMode.MACD_RSI.value} else 0,
        rsi_period + 2 if mode_upper in {StrategyMode.RSI.value, StrategyMode.MACD_RSI.value} else 0,
        3,
    )
    if len(closes) < min_bars:
        return _empty_result(candles)

    macd_curr = macd_prev = signal_curr = signal_prev = histogram_curr = None
    rsi_curr = rsi_prev = None

    if mode_upper in {StrategyMode.MACD.value, StrategyMode.MACD_RSI.value}:
        macd_line, signal_line, histogram = compute_macd_series(
            closes, fast_period, slow_period, signal_period
        )
        if len(macd_line) < 2 or len(signal_line) < 2:
            return _empty_result(candles)
        macd_prev, macd_curr = macd_line[-2], macd_line[-1]
        signal_prev, signal_curr = signal_line[-2], signal_line[-1]
        histogram_curr = histogram[-1] if histogram else None
        # Skip until SMA-seeded MACD/signal have valid (non-NaN) values.
        if (
            macd_curr != macd_curr
            or signal_curr != signal_curr
            or macd_prev != macd_prev
            or signal_prev != signal_prev
        ):
            return _empty_result(candles)

    if mode_upper in {StrategyMode.RSI.value, StrategyMode.MACD_RSI.value}:
        rsi_series = compute_rsi_series(closes, rsi_period)
        if len(rsi_series) < 2:
            return _empty_result(candles)
        rsi_prev, rsi_curr = rsi_series[-2], rsi_series[-1]

    signal = Signal.NO_SIGNAL.value
    if mode_upper == StrategyMode.MACD.value:
        signal = _macd_crossover_signal(
            macd_prev, macd_curr, signal_prev, signal_curr  # type: ignore[arg-type]
        )
    elif mode_upper == StrategyMode.RSI.value:
        signal = _rsi_crossover_signal(rsi_prev, rsi_curr, buy_level, sell_level)  # type: ignore[arg-type]
    elif mode_upper == StrategyMode.MACD_RSI.value:
        signal = _macd_rsi_combined_signal(
            macd_curr, signal_curr, rsi_curr, buy_level, sell_level  # type: ignore[arg-type]
        )

    return SignalResult(
        signal=signal,
        price=candles.last_close,
        macd=macd_curr,
        signal_line=signal_curr,
        histogram=histogram_curr,
        rsi=rsi_curr,
        macd_prev=macd_prev,
        signal_line_prev=signal_prev,
        rsi_prev=rsi_prev,
        candle_time=candles.last_timestamp,
    )
