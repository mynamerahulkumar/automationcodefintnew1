"""Market data fetching via Dhan_SRP."""

from __future__ import annotations

from dataclasses import dataclass

from core.config_loader import ConfigLoader, get_config_loader
from core.dhan_client import get_dhan_client
from core.logger import get_logger

logger = get_logger()


@dataclass
class CandleData:
    """Normalized candle series for strategy evaluation."""

    closes: list[float]
    highs: list[float]
    lows: list[float]
    timestamps: list[str]
    last_close: float | None = None
    last_high: float | None = None
    last_low: float | None = None
    last_timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.closes:
            self.last_close = self.closes[-1]
        if self.highs:
            self.last_high = self.highs[-1]
        if self.lows:
            self.last_low = self.lows[-1]
        if self.timestamps:
            self.last_timestamp = str(self.timestamps[-1])


class MarketDataService:
    """Fetches OHLCV candles and LTP for the configured instrument."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def fetch_candles(self) -> CandleData | None:
        """Fetch historical candles for strategy evaluation."""
        trading = self.config_loader.get_trading_config()
        ema = self.config_loader.get_ema_config()
        rsi = self.config_loader.get_rsi_config()

        stock_name = str(trading.get("stock_name", ""))
        exchange = str(trading.get("exchange", "NSE"))
        timeframe = self.config_loader.parse_timeframe_minutes()
        slow_ema = int(ema.get("slow", 21))
        rsi_period = int(rsi.get("period", 14))
        min_bars_needed = max(slow_ema, rsi_period) + 2

        dhan = get_dhan_client(self.config_loader)

        try:
            df = dhan.get_historical_data(stock_name, exchange, str(timeframe))
        except Exception as exc:
            logger.error("Failed to fetch candles for %s: %s", stock_name, exc)
            return None

        if df is None or getattr(df, "empty", True):
            logger.warning("Empty candle data for %s", stock_name)
            return None

        if len(df) < min_bars_needed:
            logger.warning(
                "Insufficient candles for %s: got %s, need at least %s",
                stock_name,
                len(df),
                min_bars_needed,
            )
            return None

        tail_bars = max(slow_ema * 3, rsi_period * 3, 60)
        tail = df.tail(tail_bars)

        closes = [float(x) for x in tail["close"].tolist()]
        highs = [float(x) for x in tail.get("high", tail["close"]).tolist()]
        lows = [float(x) for x in tail.get("low", tail["close"]).tolist()]
        timestamps = [str(x) for x in tail["timestamp"].tolist()]

        return CandleData(
            closes=closes,
            highs=highs,
            lows=lows,
            timestamps=timestamps,
        )

    def fetch_ltp(self) -> float | None:
        """Fetch last traded price for the configured instrument."""
        trading = self.config_loader.get_trading_config()
        from core.config_loader import resolve_instrument

        try:
            instrument = resolve_instrument(self.config_loader.get_market_config())
            symbol = instrument.get("trading_symbol") or str(trading.get("stock_name", ""))
        except (ValueError, FileNotFoundError):
            symbol = str(trading.get("stock_name", ""))

        try:
            dhan = get_dhan_client(self.config_loader)
            ltp_data = dhan.get_ltp_data(symbol)
            if isinstance(ltp_data, dict):
                for value in ltp_data.values():
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", symbol, exc)
        return None


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    """Return the shared market data service."""
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
