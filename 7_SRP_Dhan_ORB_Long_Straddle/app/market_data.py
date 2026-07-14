"""Market data fetching via Dhan_SRP (spot, option LTPs, candles)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhan_client
from app.logger import get_logger
from app.utils import safe_float

logger = get_logger()


@dataclass
class CandleBar:
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    timestamp: str | None = None


class MarketDataService:
    """Fetches LTPs and intraday candles for the underlying and option legs."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def fetch_spot(self, underlying: str | None = None) -> float | None:
        symbol = underlying or str(self.config_loader.get_trading_config().get("underlying", "NIFTY"))
        return self._ltp_for_name(symbol)

    def fetch_ltp_for_symbol(self, symbol: str) -> float | None:
        return self._ltp_for_name(symbol)

    def fetch_option_ltps(
        self,
        call_symbol: str | None,
        put_symbol: str | None,
    ) -> tuple[float | None, float | None]:
        names = [n for n in (call_symbol, put_symbol) if n]
        if not names:
            return None, None
        try:
            dhan = get_dhan_client(self.config_loader)
            data = dhan.get_ltp_data(names)
        except Exception as exc:
            logger.error("Option LTP fetch failed: %s", exc)
            return None, None

        call_ltp = self._extract_ltp(data, call_symbol) if call_symbol else None
        put_ltp = self._extract_ltp(data, put_symbol) if put_symbol else None
        return call_ltp, put_ltp

    def fetch_latest_candle(self, underlying: str | None = None, timeframe: int = 5) -> CandleBar | None:
        """Fetch latest intraday bar. Dhan_SRP supports 2/3/5/10/15/30/60 minute frames."""
        trading = self.config_loader.get_trading_config()
        symbol = underlying or str(trading.get("underlying", "NIFTY"))
        exchange = str(trading.get("exchange", "NSE"))
        tf = timeframe if timeframe in {2, 3, 5, 10, 15, 30, 60} else 5
        try:
            dhan = get_dhan_client(self.config_loader)
            df = dhan.get_intraday_data(symbol, exchange, str(tf))
        except Exception as exc:
            logger.error("Intraday candle fetch failed for %s: %s", symbol, exc)
            return None

        if df is None or getattr(df, "empty", True):
            return None

        row = df.iloc[-1]
        ts = None
        for col in ("timestamp", "datetime", "date", "time"):
            if col in df.columns:
                ts = str(row[col])
                break
        return CandleBar(
            open=safe_float(row.get("open") if hasattr(row, "get") else row["open"]),
            high=safe_float(row.get("high") if hasattr(row, "get") else row["high"]),
            low=safe_float(row.get("low") if hasattr(row, "get") else row["low"]),
            close=safe_float(row.get("close") if hasattr(row, "get") else row["close"]),
            timestamp=ts,
        )

    def fetch_opening_range(
        self,
        underlying: str,
        opening_range_minutes: int,
        bar_minutes: int = 5,
    ) -> tuple[float | None, float | None]:
        """Compute ORB high/low from first N intraday bars covering the opening window."""
        trading = self.config_loader.get_trading_config()
        exchange = str(trading.get("exchange", "NSE"))
        tf = bar_minutes if bar_minutes in {2, 3, 5, 10, 15, 30, 60} else 5
        try:
            dhan = get_dhan_client(self.config_loader)
            df = dhan.get_intraday_data(underlying, exchange, str(tf))
        except Exception as exc:
            logger.error("ORB candle fetch failed: %s", exc)
            return None, None

        if df is None or getattr(df, "empty", True):
            return None, None

        bars = max(1, int(opening_range_minutes / tf))
        window = df.head(bars)
        try:
            high = float(window["high"].max())
            low = float(window["low"].min())
            return high, low
        except Exception as exc:
            logger.error("ORB high/low computation failed: %s", exc)
            return None, None

    def _ltp_for_name(self, name: str) -> float | None:
        try:
            dhan = get_dhan_client(self.config_loader)
            data = dhan.get_ltp_data(name)
            return self._extract_ltp(data, name)
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", name, exc)
            return None

    @staticmethod
    def _extract_ltp(data: Any, name: str | None) -> float | None:
        if not isinstance(data, dict) or not name:
            if isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
            return None
        upper = name.upper()
        for key, value in data.items():
            if str(key).upper() == upper and isinstance(value, (int, float)):
                return float(value)
        for key, value in data.items():
            if upper in str(key).upper() and isinstance(value, (int, float)):
                return float(value)
        for value in data.values():
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
