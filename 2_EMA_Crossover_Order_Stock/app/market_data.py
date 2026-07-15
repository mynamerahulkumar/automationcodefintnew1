"""Market data fetching via Dhan_SRP (security_id path — low memory)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhan_client
from app.logger import get_logger
from app.security_master import resolve_instrument

logger = get_logger()


@dataclass
class CandleData:
    """Normalized candle series for strategy evaluation."""

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
    """Fetches OHLCV candles for strategy evaluation."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def _resolved(self) -> dict:
        return resolve_instrument(self.config_loader.get_trading_config())

    def fetch_candles(self) -> CandleData | None:
        """Fetch historical candles using security_id (avoids full-CSV copies)."""
        trading = self.config_loader.get_trading_config()
        strategy = self.config_loader.get_strategy_config()
        stock_name = str(trading.get("stock_name", ""))
        timeframe = self.config_loader.parse_timeframe_minutes()
        slow_ema = int(strategy.get("slow_ema", 21))

        try:
            instrument = self._resolved()
        except (ValueError, FileNotFoundError) as exc:
            logger.error("Instrument resolve failed: %s", exc)
            return None

        security_id = str(instrument["security_id"])
        exchange_segment = str(instrument["exchange_segment"])
        instrument_type = str(instrument.get("instrument_name", "EQUITY"))

        dhan = get_dhan_client(self.config_loader)

        # Enough session days for slow EMA on intraday bars
        days_back = max(5, (slow_ema * 3 * timeframe) // (6 * 60) + 2)
        to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime(
            "%Y-%m-%d"
        )

        try:
            # Prefer lightweight SDK path with known security_id
            df = dhan.get_history_df(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=str(timeframe),
            )
        except Exception as exc:
            logger.warning(
                "get_history_df failed (%s); falling back to get_historical_data",
                exc,
            )
            try:
                df = dhan.get_historical_data(stock_name, str(trading.get("exchange", "NSE")), str(timeframe))
            except Exception as exc2:
                logger.error("Failed to fetch candles for %s: %s", stock_name, exc2)
                return None

        if df is None or getattr(df, "empty", True):
            logger.warning("Empty candle data for %s", stock_name)
            return None

        if "close" not in df.columns:
            logger.error("Candle data missing close column for %s", stock_name)
            return None

        min_bars = max(slow_ema * 3, 60)
        if len(df) < slow_ema + 2:
            logger.warning(
                "Insufficient candles for %s: got %s, need at least %s",
                stock_name,
                len(df),
                slow_ema + 2,
            )
            return None

        tail = df.tail(min_bars)
        closes = [float(x) for x in tail["close"].tolist()]
        if "timestamp" in tail.columns:
            timestamps = [str(x) for x in tail["timestamp"].tolist()]
        else:
            timestamps = [str(i) for i in range(len(closes))]

        return CandleData(closes=closes, timestamps=timestamps)

    def fetch_ltp(self) -> float | None:
        """Fetch LTP via quote API when possible (avoids scanning full instrument DF)."""
        trading = self.config_loader.get_trading_config()
        stock_name = str(trading.get("stock_name", ""))

        try:
            instrument = self._resolved()
        except (ValueError, FileNotFoundError):
            instrument = {
                "security_id": trading.get("security_id"),
                "exchange_segment": "NSE_EQ",
                "trading_symbol": stock_name,
            }

        security_id = instrument.get("security_id")
        exchange_segment = str(instrument.get("exchange_segment") or "NSE_EQ")
        symbol = str(instrument.get("trading_symbol") or stock_name)

        try:
            dhan = get_dhan_client(self.config_loader)

            # Prefer quote_data with security_id — lighter than get_ltp_data
            quote_fn = getattr(getattr(dhan, "Dhan", None), "quote_data", None) or getattr(
                getattr(dhan, "Dhan", None), "ohlc_data", None
            )
            if quote_fn and security_id:
                payload = {exchange_segment: [int(security_id)]}
                raw = quote_fn(payload)
                price = self._extract_ltp(raw, str(security_id))
                if price is not None:
                    return price

            ltp_data = dhan.get_ltp_data(symbol)
            if isinstance(ltp_data, dict):
                for value in ltp_data.values():
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", symbol, exc)
        return None

    @staticmethod
    def _extract_ltp(raw: dict | None, security_id: str) -> float | None:
        """Best-effort parse of Dhan quote/ohlc response for LTP."""
        if not isinstance(raw, dict):
            return None
        data = raw.get("data") if "data" in raw else raw
        if not isinstance(data, dict):
            return None

        # Nested by segment then security_id
        for segment_data in data.values():
            if not isinstance(segment_data, dict):
                continue
            entry = segment_data.get(security_id) or segment_data.get(int(security_id)) if security_id.isdigit() else None
            if isinstance(entry, dict):
                for key in ("last_price", "LTP", "ltp", "last_trade_price", "close"):
                    val = entry.get(key)
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)
                ohlc = entry.get("ohlc") if isinstance(entry.get("ohlc"), dict) else {}
                for key in ("close", "last_price", "ltp"):
                    val = ohlc.get(key)
                    if isinstance(val, (int, float)) and val > 0:
                        return float(val)
        return None


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    """Return the shared market data service instance."""
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
