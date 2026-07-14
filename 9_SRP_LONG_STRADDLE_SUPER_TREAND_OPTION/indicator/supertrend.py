"""Pure Python Supertrend (ATR-based) indicator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SupertrendDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


@dataclass
class SupertrendResult:
    """Supertrend evaluation output for strategy and CLI/API consumers."""

    value: float | None = None
    atr: float | None = None
    direction: SupertrendDirection = SupertrendDirection.NEUTRAL
    candle_time: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "atr": self.atr,
            "direction": self.direction.value,
            "candle_time": self.candle_time,
        }


def compute_true_range(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> list[float]:
    """Compute True Range series."""
    if not highs or len(highs) != len(lows) or len(highs) != len(closes):
        return []
    trs: list[float] = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return trs


def compute_atr(true_ranges: list[float], length: int) -> list[float | None]:
    """Wilder ATR series; None until enough bars."""
    if length <= 0 or not true_ranges:
        return []
    atrs: list[float | None] = [None] * len(true_ranges)
    if len(true_ranges) < length:
        return atrs
    seed = sum(true_ranges[:length]) / length
    atrs[length - 1] = seed
    atr = seed
    for i in range(length, len(true_ranges)):
        atr = ((atr * (length - 1)) + true_ranges[i]) / length
        atrs[i] = atr
    return atrs


class SupertrendEngine:
    """Compute Supertrend direction from OHLC bars."""

    def __init__(self, length: int = 10, multiplier: float = 3.0) -> None:
        self.length = length
        self.multiplier = multiplier

    def evaluate(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        *,
        last_timestamp: str | None = None,
    ) -> SupertrendResult:
        """Return latest Supertrend value and BUY/SELL direction."""
        n = len(closes)
        if n < self.length + 2 or n != len(highs) or n != len(lows):
            return SupertrendResult(candle_time=last_timestamp)

        trs = compute_true_range(highs, lows, closes)
        atrs = compute_atr(trs, self.length)

        final_upper: list[float | None] = [None] * n
        final_lower: list[float | None] = [None] * n
        supertrend: list[float | None] = [None] * n
        direction: list[SupertrendDirection] = [SupertrendDirection.NEUTRAL] * n

        for i in range(n):
            atr = atrs[i]
            if atr is None:
                continue
            hl2 = (highs[i] + lows[i]) / 2.0
            basic_upper = hl2 + self.multiplier * atr
            basic_lower = hl2 - self.multiplier * atr

            if i == 0 or final_upper[i - 1] is None:
                final_upper[i] = basic_upper
            else:
                prev_fu = final_upper[i - 1]
                assert prev_fu is not None
                if basic_upper < prev_fu or closes[i - 1] > prev_fu:
                    final_upper[i] = basic_upper
                else:
                    final_upper[i] = prev_fu

            if i == 0 or final_lower[i - 1] is None:
                final_lower[i] = basic_lower
            else:
                prev_fl = final_lower[i - 1]
                assert prev_fl is not None
                if basic_lower > prev_fl or closes[i - 1] < prev_fl:
                    final_lower[i] = basic_lower
                else:
                    final_lower[i] = prev_fl

            fu = final_upper[i]
            fl = final_lower[i]
            assert fu is not None and fl is not None

            if i == 0 or supertrend[i - 1] is None:
                if closes[i] <= fu:
                    supertrend[i] = fu
                    direction[i] = SupertrendDirection.SELL
                else:
                    supertrend[i] = fl
                    direction[i] = SupertrendDirection.BUY
                continue

            prev_st = supertrend[i - 1]
            prev_dir = direction[i - 1]
            assert prev_st is not None

            if prev_dir == SupertrendDirection.BUY:
                if closes[i] < fl:
                    supertrend[i] = fu
                    direction[i] = SupertrendDirection.SELL
                else:
                    supertrend[i] = fl
                    direction[i] = SupertrendDirection.BUY
            else:
                if closes[i] > fu:
                    supertrend[i] = fl
                    direction[i] = SupertrendDirection.BUY
                else:
                    supertrend[i] = fu
                    direction[i] = SupertrendDirection.SELL

        last = n - 1
        return SupertrendResult(
            value=supertrend[last],
            atr=atrs[last],
            direction=direction[last],
            candle_time=last_timestamp,
        )
