"""EMA, RSI, and combined EMA+RSI strategy implementations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from core.market_data import CandleData


class StrategyMode(str, Enum):
    """Supported strategy modes."""

    EMA = "EMA"
    RSI = "RSI"
    EMA_RSI = "EMA_RSI"


class Signal(str, Enum):
    """Trading signal values."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class SignalResult:
    """Strategy evaluation output."""

    signal: str
    price: float | None
    ema_fast: float | None
    ema_slow: float | None
    rsi: float | None
    ema_fast_prev: float | None = None
    ema_slow_prev: float | None = None
    rsi_prev: float | None = None
    candle_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "price": self.price,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "rsi": self.rsi,
            "candle_time": self.candle_time,
        }


def compute_ema_series(closes: list[float], period: int) -> list[float]:
    """
    Compute EMA series using incremental formula (no pandas in hot path).

    Fast EMA — smaller period (e.g. 5, 8, 9, 10, 13). Responds faster to price.
    Slow EMA — larger period (e.g. 20, 21, 34, 50, 100, 200). Responds slower.
    """
    if not closes or period <= 0:
        return []

    k = 2.0 / (period + 1)
    ema_values: list[float] = []
    ema = float(closes[0])
    ema_values.append(ema)

    for price in closes[1:]:
        ema = float(price) * k + ema * (1.0 - k)
        ema_values.append(ema)

    return ema_values


def compute_rsi_series(closes: list[float], period: int) -> list[float]:
    """
    Compute RSI series using Wilder's smoothing.

    Default period: 14.
    Buy level examples: 60 default, 55 aggressive, 65 conservative.
    Sell level examples: 40 default, 45 aggressive, 35 conservative.
    """
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


def _empty_result(candles: CandleData) -> SignalResult:
    return SignalResult(
        signal=Signal.HOLD.value,
        price=candles.last_close,
        ema_fast=None,
        ema_slow=None,
        rsi=None,
        candle_time=candles.last_timestamp,
    )


def _ema_crossover_signal(
    fast_prev: float,
    fast_curr: float,
    slow_prev: float,
    slow_curr: float,
) -> str:
    """EMA only: crossover on last two completed values."""
    if fast_prev <= slow_prev and fast_curr > slow_curr:
        return Signal.BUY.value
    if fast_prev >= slow_prev and fast_curr < slow_curr:
        return Signal.SELL.value
    return Signal.HOLD.value


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
    return Signal.HOLD.value


def _ema_rsi_combined_signal(
    fast_curr: float,
    slow_curr: float,
    rsi_curr: float,
    buy_level: float,
    sell_level: float,
) -> str:
    """EMA+RSI: both indicators must agree (level-based, not crossover)."""
    if fast_curr > slow_curr and rsi_curr > buy_level:
        return Signal.BUY.value
    if fast_curr < slow_curr and rsi_curr < sell_level:
        return Signal.SELL.value
    return Signal.HOLD.value


def generate_signal(
    mode: str,
    candles: CandleData,
    ema_config: dict[str, Any],
    rsi_config: dict[str, Any],
) -> SignalResult:
    """
    Evaluate the active strategy and return BUY, SELL, or HOLD.

    The trading engine calls this without knowing which strategy is active.
    """
    mode_upper = str(mode).upper()
    closes = candles.closes

    fast_period = int(ema_config.get("fast", 9))
    slow_period = int(ema_config.get("slow", 21))
    rsi_period = int(rsi_config.get("period", 14))
    buy_level = float(rsi_config.get("buy", 60))
    sell_level = float(rsi_config.get("sell", 40))

    min_bars = max(
        slow_period + 2 if mode_upper in {StrategyMode.EMA.value, StrategyMode.EMA_RSI.value} else 0,
        rsi_period + 2 if mode_upper in {StrategyMode.RSI.value, StrategyMode.EMA_RSI.value} else 0,
        3,
    )
    if len(closes) < min_bars:
        return _empty_result(candles)

    ema_fast_curr = ema_fast_prev = ema_slow_curr = ema_slow_prev = None
    rsi_curr = rsi_prev = None

    if mode_upper in {StrategyMode.EMA.value, StrategyMode.EMA_RSI.value}:
        fast_series = compute_ema_series(closes, fast_period)
        slow_series = compute_ema_series(closes, slow_period)
        if len(fast_series) < 2 or len(slow_series) < 2:
            return _empty_result(candles)
        ema_fast_prev, ema_fast_curr = fast_series[-2], fast_series[-1]
        ema_slow_prev, ema_slow_curr = slow_series[-2], slow_series[-1]

    if mode_upper in {StrategyMode.RSI.value, StrategyMode.EMA_RSI.value}:
        rsi_series = compute_rsi_series(closes, rsi_period)
        if len(rsi_series) < 2:
            return _empty_result(candles)
        rsi_prev, rsi_curr = rsi_series[-2], rsi_series[-1]

    signal = Signal.HOLD.value
    if mode_upper == StrategyMode.EMA.value:
        signal = _ema_crossover_signal(
            ema_fast_prev, ema_fast_curr, ema_slow_prev, ema_slow_curr  # type: ignore[arg-type]
        )
    elif mode_upper == StrategyMode.RSI.value:
        signal = _rsi_crossover_signal(rsi_prev, rsi_curr, buy_level, sell_level)  # type: ignore[arg-type]
    elif mode_upper == StrategyMode.EMA_RSI.value:
        signal = _ema_rsi_combined_signal(
            ema_fast_curr, ema_slow_curr, rsi_curr, buy_level, sell_level  # type: ignore[arg-type]
        )

    return SignalResult(
        signal=signal,
        price=candles.last_close,
        ema_fast=ema_fast_curr,
        ema_slow=ema_slow_curr,
        rsi=rsi_curr,
        ema_fast_prev=ema_fast_prev,
        ema_slow_prev=ema_slow_prev,
        rsi_prev=rsi_prev,
        candle_time=candles.last_timestamp,
    )
