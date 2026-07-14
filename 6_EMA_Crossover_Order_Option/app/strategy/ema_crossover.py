"""EMA crossover strategy implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.market_data import CandleData


@dataclass
class SignalResult:
    """Strategy evaluation output."""

    signal: str | None
    fast_ema: float | None
    slow_ema: float | None
    candle_time: str | None
    fast_ema_prev: float | None = None
    slow_ema_prev: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "fast_ema": self.fast_ema,
            "slow_ema": self.slow_ema,
            "candle_time": self.candle_time,
            "fast_ema_prev": self.fast_ema_prev,
            "slow_ema_prev": self.slow_ema_prev,
        }


def compute_ema_series(prices: list[float], period: int) -> list[float]:
    """Compute EMA series using incremental formula (no pandas in hot path)."""
    if not prices or period <= 0:
        return []

    k = 2.0 / (period + 1)
    ema_values: list[float] = []
    ema = prices[0]
    ema_values.append(ema)

    for price in prices[1:]:
        ema = price * k + ema * (1.0 - k)
        ema_values.append(ema)

    return ema_values


class EmaCrossoverStrategy:
    """Detect EMA crossover signals on confirmed candle close."""

    def __init__(self, fast_ema: int = 9, slow_ema: int = 21) -> None:
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema

    def evaluate(self, candles: CandleData) -> SignalResult:
        """Evaluate crossover on the last two completed candles."""
        closes = candles.closes
        if len(closes) < self.slow_ema + 2:
            return SignalResult(
                signal=None,
                fast_ema=None,
                slow_ema=None,
                candle_time=candles.last_timestamp,
            )

        fast_series = compute_ema_series(closes, self.fast_ema)
        slow_series = compute_ema_series(closes, self.slow_ema)

        fast_prev, fast_curr = fast_series[-2], fast_series[-1]
        slow_prev, slow_curr = slow_series[-2], slow_series[-1]

        signal: str | None = None
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            signal = "BUY"
        elif fast_prev >= slow_prev and fast_curr < slow_curr:
            signal = "SELL"

        return SignalResult(
            signal=signal,
            fast_ema=round(fast_curr, 4),
            slow_ema=round(slow_curr, 4),
            candle_time=candles.last_timestamp,
            fast_ema_prev=round(fast_prev, 4),
            slow_ema_prev=round(slow_prev, 4),
        )
