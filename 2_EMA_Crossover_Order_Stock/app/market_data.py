"""Market data fetching via Dhan SDK security_id path (low memory, no hangs)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pandas as pd

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhan_client
from app.logger import flush_logger, get_logger
from app.security_master import resolve_instrument

logger = get_logger()

# Dhan intraday charts only support the last ~5 trading days
INTRADAY_DAYS = 5
VALID_INTERVALS = {1, 5, 15, 25, 60}


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
        """Fetch intraday candles using security_id via Dhan charts API."""
        trading = self.config_loader.get_trading_config()
        strategy = self.config_loader.get_strategy_config()
        stock_name = str(trading.get("stock_name", ""))
        timeframe = self.config_loader.parse_timeframe_minutes()
        slow_ema = int(strategy.get("slow_ema", 21))

        if timeframe not in VALID_INTERVALS:
            logger.error(
                "Unsupported timeframe minutes=%s (Dhan allows %s)",
                timeframe,
                sorted(VALID_INTERVALS),
            )
            return None

        try:
            instrument = self._resolved()
        except (ValueError, FileNotFoundError) as exc:
            logger.error("Instrument resolve failed: %s", exc)
            return None

        security_id = str(instrument["security_id"])
        exchange_segment = str(instrument["exchange_segment"])
        instrument_type = str(instrument.get("instrument_name") or "EQUITY")

        to_date = datetime.datetime.now().strftime("%Y-%m-%d")
        from_date = (
            datetime.datetime.now() - datetime.timedelta(days=INTRADAY_DAYS)
        ).strftime("%Y-%m-%d")

        logger.info(
            "Fetching candles: %s id=%s segment=%s interval=%sm from=%s to=%s",
            stock_name,
            security_id,
            exchange_segment,
            timeframe,
            from_date,
            to_date,
        )
        flush_logger()

        try:
            dhan = get_dhan_client(self.config_loader)
            response = dhan.Dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=int(timeframe),
            )
        except Exception as exc:
            logger.error("Candle API call failed for %s: %s", stock_name, exc)
            flush_logger()
            return None

        if not isinstance(response, dict) or response.get("status") == "failure":
            logger.error("Candle API failure for %s: %s", stock_name, response)
            flush_logger()
            return None

        data = response.get("data")
        if not data:
            logger.warning("Empty candle payload for %s: %s", stock_name, response)
            flush_logger()
            return None

        try:
            df = pd.DataFrame(data)
        except Exception as exc:
            logger.error("Could not parse candle data for %s: %s", stock_name, exc)
            return None

        if df.empty or "close" not in df.columns:
            logger.warning("No close prices for %s (cols=%s)", stock_name, list(df.columns))
            return None

        if "timestamp" in df.columns:
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(
                    "Asia/Kolkata"
                )
            except Exception:
                df["timestamp"] = df["timestamp"].astype(str)

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

        logger.info("Candles ready for %s: %s bars, last_close=%s", stock_name, len(closes), closes[-1])
        flush_logger()
        return CandleData(closes=closes, timestamps=timestamps)

    def fetch_ltp(self) -> float | None:
        """Fetch LTP via ohlc/quote API; never call heavy get_ltp_data on cloud."""
        trading = self.config_loader.get_trading_config()
        stock_name = str(trading.get("stock_name", ""))

        try:
            instrument = self._resolved()
        except (ValueError, FileNotFoundError) as exc:
            logger.error("LTP resolve failed: %s", exc)
            return None

        security_id = str(instrument["security_id"])
        exchange_segment = str(instrument.get("exchange_segment") or "NSE_EQ")

        try:
            dhan = get_dhan_client(self.config_loader)
            sdk = dhan.Dhan
            payload = {exchange_segment: [int(security_id)]}

            for method_name in ("ohlc_data", "quote_data", "ticker_data"):
                fn = getattr(sdk, method_name, None)
                if not callable(fn):
                    continue
                try:
                    raw = fn(payload)
                    price = self._extract_ltp(raw, security_id)
                    if price is not None:
                        return price
                except Exception as exc:
                    logger.warning("%s failed for %s: %s", method_name, stock_name, exc)
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", stock_name, exc)
        return None

    @staticmethod
    def _extract_ltp(raw: dict | None, security_id: str) -> float | None:
        """Best-effort parse of Dhan quote/ohlc response for LTP."""
        if not isinstance(raw, dict):
            return None
        data = raw.get("data") if "data" in raw else raw
        if not isinstance(data, dict):
            return None

        for segment_data in data.values():
            if not isinstance(segment_data, dict):
                continue
            entry = segment_data.get(security_id)
            if entry is None and security_id.isdigit():
                entry = segment_data.get(int(security_id))
            if not isinstance(entry, dict):
                continue
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
