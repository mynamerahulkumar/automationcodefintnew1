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


@dataclass
class CandleSeries:
    """Normalized close series for EMA evaluation."""

    closes: list[float]
    timestamps: list[str]
    last_close: float | None = None
    last_timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.closes:
            self.last_close = self.closes[-1]
        if self.timestamps:
            self.last_timestamp = str(self.timestamps[-1])


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

    def fetch_candle_series(
        self,
        underlying: str | None = None,
        timeframe: int | None = None,
        min_bars: int | None = None,
    ) -> CandleSeries | None:
        """Fetch close series for EMA calculation (tail only to limit memory)."""
        trading = self.config_loader.get_trading_config()
        ema_cfg = self.config_loader.get_ema_config()
        symbol = underlying or str(trading.get("underlying", "NIFTY"))
        exchange = str(trading.get("exchange", "NSE"))
        slow = int(ema_cfg.get("slow", 21))
        tf = timeframe if timeframe is not None else int(ema_cfg.get("timeframe_minutes", 5))
        tf = tf if tf in {2, 3, 5, 10, 15, 30, 60} else 5
        need = min_bars if min_bars is not None else max(slow * 3, 60)

        try:
            dhan = get_dhan_client(self.config_loader)
            # Prefer intraday for same-day EMA; fall back to historical helper.
            df = None
            if hasattr(dhan, "get_intraday_data"):
                try:
                    df = dhan.get_intraday_data(symbol, exchange, str(tf))
                except Exception:
                    df = None
            if (df is None or getattr(df, "empty", True)) and hasattr(dhan, "get_historical_data"):
                df = dhan.get_historical_data(symbol, exchange, str(tf))
        except Exception as exc:
            logger.error("Candle series fetch failed for %s: %s", symbol, exc)
            return None

        if df is None or getattr(df, "empty", True):
            logger.warning("Empty candle series for %s", symbol)
            return None

        if len(df) < slow + 2:
            logger.warning(
                "Insufficient candles for %s: got %s, need at least %s",
                symbol,
                len(df),
                slow + 2,
            )
            return None

        tail = df.tail(need)
        closes = [float(x) for x in tail["close"].tolist()]
        timestamps: list[str] = []
        for col in ("timestamp", "datetime", "date", "time"):
            if col in tail.columns:
                timestamps = [str(x) for x in tail[col].tolist()]
                break
        if not timestamps:
            timestamps = [str(i) for i in range(len(closes))]

        return CandleSeries(closes=closes, timestamps=timestamps)

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
