"""Reusable EMA calculation and crossover detection (no pandas)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class EmaTrend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class EmaResult:
    """EMA evaluation output for strategy and CLI/API consumers."""

    fast_ema: float | None = None
    slow_ema: float | None = None
    fast_ema_prev: float | None = None
    slow_ema_prev: float | None = None
    trend: EmaTrend = EmaTrend.NEUTRAL
    cross_detected: bool = False
    cross_direction: str | None = None  # BULLISH | BEARISH | None
    candle_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "fast_ema_prev": self.fast_ema_prev,
            "slow_ema_prev": self.slow_ema_prev,
            "trend": self.trend.value,
            "cross_detected": self.cross_detected,
            "cross_direction": self.cross_direction,
            "candle_time": self.candle_time,
        }


def compute_ema_series(prices: list[float], period: int) -> list[float]:
    """
    Compute EMA series using TradingView-style SMA seed.

    First ``period`` closes form an SMA seed; subsequent values use the
    standard EMA formula. Early bars before the seed are left as NaN so
    the series stays aligned with ``prices``.
    """
    if not prices or period <= 0 or len(prices) < period:
        return []

    k = 2.0 / (period + 1)
    ema_values: list[float] = [float("nan")] * (period - 1)

    ema = sum(prices[:period]) / float(period)
    ema_values.append(ema)

    for price in prices[period:]:
        ema = float(price) * k + ema * (1.0 - k)
        ema_values.append(ema)

    return ema_values


def _finite(value: float | None) -> bool:
    return value is not None and not math.isnan(value) and math.isfinite(value)


class EmaEngine:
    """Detect EMA crossover signals on confirmed candle closes."""

    def __init__(self, fast: int = 9, slow: int = 21) -> None:
        self.fast = fast
        self.slow = slow

    def evaluate(
        self,
        closes: list[float],
        *,
        last_timestamp: str | None = None,
    ) -> EmaResult:
        """Evaluate trend and crossover on the last two completed candles."""
        if len(closes) < self.slow + 2:
            return EmaResult(candle_time=last_timestamp)

        fast_series = compute_ema_series(closes, self.fast)
        slow_series = compute_ema_series(closes, self.slow)
        if not fast_series or not slow_series:
            return EmaResult(candle_time=last_timestamp)

        # Walk back to find two finite pairs (skip SMA-seed padding NaNs).
        pairs: list[tuple[float, float]] = []
        for i in range(len(closes) - 1, -1, -1):
            if i >= len(fast_series) or i >= len(slow_series):
                continue
            f_val, s_val = fast_series[i], slow_series[i]
            if _finite(f_val) and _finite(s_val):
                pairs.append((float(f_val), float(s_val)))
            if len(pairs) >= 2:
                break

        if len(pairs) < 2:
            return EmaResult(candle_time=last_timestamp)

        fast_curr, slow_curr = pairs[0]
        fast_prev, slow_prev = pairs[1]

        if fast_curr > slow_curr:
            trend = EmaTrend.BULLISH
        elif fast_curr < slow_curr:
            trend = EmaTrend.BEARISH
        else:
            trend = EmaTrend.NEUTRAL

        cross_detected = False
        cross_direction: str | None = None
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            cross_detected = True
            cross_direction = "BULLISH"
        elif fast_prev >= slow_prev and fast_curr < slow_curr:
            cross_detected = True
            cross_direction = "BEARISH"

        return EmaResult(
            fast_ema=round(fast_curr, 4),
            slow_ema=round(slow_curr, 4),
            fast_ema_prev=round(fast_prev, 4),
            slow_ema_prev=round(slow_prev, 4),
            trend=trend,
            cross_detected=cross_detected,
            cross_direction=cross_direction,
            candle_time=last_timestamp,
        )
