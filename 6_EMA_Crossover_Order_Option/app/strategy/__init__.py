"""Pluggable trading strategies and factory."""

from __future__ import annotations

from typing import Protocol

from app.config_loader import ConfigLoader, get_config_loader
from app.market_data import CandleData
from app.strategy.ema_crossover import EmaCrossoverStrategy, SignalResult


class BaseStrategy(Protocol):
    """Protocol for trading strategies."""

    def evaluate(self, candles: CandleData) -> SignalResult:
        """Evaluate market data and return a signal result."""


STRATEGIES: dict[str, type] = {
    "EMA_CROSSOVER": EmaCrossoverStrategy,
}


def get_strategy(config_loader: ConfigLoader | None = None) -> BaseStrategy:
    """Instantiate the strategy selected in config.yaml."""
    loader = config_loader or get_config_loader()
    strategy_cfg = loader.get_strategy_config()
    name = str(strategy_cfg.get("name", "EMA_CROSSOVER")).upper()

    if name not in STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}")

    if name == "EMA_CROSSOVER":
        return EmaCrossoverStrategy(
            fast_ema=int(strategy_cfg.get("fast_ema", 9)),
            slow_ema=int(strategy_cfg.get("slow_ema", 21)),
        )

    return STRATEGIES[name]()
