"""Market data fetching via lightweight REST client (no Dhan_SRP / pandas)."""

from __future__ import annotations

import gc
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

try:
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
except ImportError:  # Python < 3.9
    import pytz

    IST = pytz.timezone("Asia/Kolkata")

from core.config_loader import ConfigLoader, get_config_loader, resolve_instrument
from core.dhan_client import get_dhanhq_lite
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


def _parse_candle_date(timestamp: str) -> date | None:
    """Extract calendar date from a candle timestamp string."""
    text = str(timestamp).strip()
    if not text:
        return None
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _ist_today() -> date:
    return datetime.now(IST).date()


def _format_api_error(response: Any) -> str:
    if not isinstance(response, dict):
        return str(response)
    remarks = response.get("remarks") or {}
    if isinstance(remarks, dict):
        code = remarks.get("error_code") or remarks.get("code") or ""
        message = remarks.get("error_message") or remarks.get("message") or ""
        if code or message:
            return f"{code} {message}".strip()
    return str(response.get("remarks") or response.get("message") or response)


class MarketDataService:
    """Fetches OHLCV candles and LTP for the configured instrument."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self._ltp_cache: float | None = None
        self._ltp_cache_at: float = 0.0

    def _resolved_instrument(self) -> dict:
        try:
            return self.config_loader.get_resolved_instrument()
        except Exception:
            try:
                return resolve_instrument(self.config_loader.get_market_config())
            except Exception:
                return {}

    def _exchange_segment(self, instrument: dict, exchange: str) -> str:
        segment = str(instrument.get("exchange_segment") or "").strip()
        if segment:
            return segment
        return "NSE_EQ" if exchange.upper() == "NSE" else "BSE_EQ"

    def _cache_ltp(self, price: float) -> float:
        import time

        self._ltp_cache = price
        self._ltp_cache_at = time.monotonic()
        return price

    def _cached_ltp(self, max_age_seconds: float = 15.0) -> float | None:
        import time

        if self._ltp_cache is None:
            return None
        if time.monotonic() - self._ltp_cache_at > max_age_seconds:
            return None
        return self._ltp_cache

    def _sync_today_daily_candle(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        timestamps: list[str],
    ) -> tuple[list[float], list[float], list[float], list[str]]:
        """
        Dhan daily history often omits the current session bar.

        Merge LTP into today's daily candle so MACD/RSI match live charts.
        """
        ltp = self.fetch_ltp()
        if ltp is None or ltp <= 0 or not timestamps:
            return closes, highs, lows, timestamps

        today = _ist_today()
        last_day = _parse_candle_date(timestamps[-1])
        today_label = today.isoformat()

        if last_day == today:
            closes[-1] = ltp
            highs[-1] = max(highs[-1], ltp)
            lows[-1] = min(lows[-1], ltp)
            return closes, highs, lows, timestamps

        if last_day is None or last_day < today:
            closes.append(ltp)
            highs.append(ltp)
            lows.append(ltp)
            timestamps.append(today_label)
            logger.info(
                "Appended today's daily candle from LTP=%.2f (history ended %s)",
                ltp,
                last_day,
            )
        return closes, highs, lows, timestamps

    def _parse_ohlc_payload(
        self,
        payload: Any,
        dhan: Any,
    ) -> tuple[list[float], list[float], list[float], list[str]] | None:
        """Convert Dhan OHLC dict/list payload into plain Python lists (no pandas)."""
        if not isinstance(payload, dict):
            return None

        closes_raw = payload.get("close")
        if closes_raw is None:
            return None

        highs_raw = payload.get("high", closes_raw)
        lows_raw = payload.get("low", closes_raw)
        ts_raw = payload.get("timestamp", [])

        closes = [float(x) for x in closes_raw]
        highs = [float(x) for x in highs_raw]
        lows = [float(x) for x in lows_raw]
        timestamps: list[str] = []
        for ts in ts_raw:
            try:
                timestamps.append(str(dhan.convert_to_date_time(ts)))
            except Exception:
                timestamps.append(str(ts))

        if len(timestamps) != len(closes):
            timestamps = [str(i) for i in range(len(closes))]

        return closes, highs, lows, timestamps

    def fetch_candles(self) -> CandleData | None:
        """Fetch historical candles for strategy evaluation."""
        trading = self.config_loader.get_trading_config()
        macd = self.config_loader.get_macd_config()
        rsi = self.config_loader.get_rsi_config()

        stock_name = str(trading.get("stock_name", ""))
        exchange = str(trading.get("exchange", "NSE"))
        timeframe = self.config_loader.get_dhan_timeframe()
        slow_period = int(macd.get("slow", 26))
        signal_period = int(macd.get("signal", 9))
        rsi_period = int(rsi.get("period", 14))
        min_bars_needed = max(slow_period + signal_period, rsi_period) + 2

        instrument = self._resolved_instrument()
        security_id = str(instrument.get("security_id") or "").strip()
        if not security_id:
            logger.error(
                "Failed to fetch candles for %s — security_id missing in config",
                stock_name,
            )
            return None

        instrument_type = str(instrument.get("instrument_name") or "EQUITY")
        exchange_segment = self._exchange_segment(instrument, exchange)

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            to_date = _ist_today()
            # Dhan daily toDate is non-inclusive — use tomorrow so today is included.
            api_to = (to_date + timedelta(days=1)).isoformat()
            if timeframe == "DAY":
                from_date = to_date - timedelta(days=400)
                response = dhan.historical_daily_data(
                    security_id,
                    exchange_segment,
                    instrument_type,
                    from_date.isoformat(),
                    api_to,
                    0,
                )
            else:
                interval = int(timeframe)
                from_date = to_date - timedelta(days=5)
                response = dhan.intraday_minute_data(
                    security_id,
                    exchange_segment,
                    instrument_type,
                    from_date.isoformat(),
                    api_to,
                    interval,
                )
        except MemoryError:
            logger.error(
                "Failed to fetch candles for %s — MemoryError on low-RAM host; "
                "free RAM or reduce lookback",
                stock_name,
            )
            gc.collect()
            return None
        except Exception as exc:
            logger.error("Failed to fetch candles for %s: %s", stock_name, exc)
            return None

        if not isinstance(response, dict) or response.get("status") == "failure":
            logger.error(
                "Failed to fetch candles for %s — Dhan API error: %s",
                stock_name,
                _format_api_error(response),
            )
            return None

        parsed = self._parse_ohlc_payload(response.get("data") or {}, dhan)
        if parsed is None:
            logger.warning("Empty candle data for %s", stock_name)
            return None

        closes, highs, lows, timestamps = parsed
        if len(closes) < min_bars_needed:
            logger.warning(
                "Insufficient candles for %s: got %s, need at least %s",
                stock_name,
                len(closes),
                min_bars_needed,
            )
            return None

        # Keep lookback modest for 1GB hosts while still converging MACD/RSI.
        if timeframe == "DAY":
            tail_bars = max(slow_period * 15, rsi_period * 15, 200)
        else:
            tail_bars = max(slow_period * 3, rsi_period * 3, 120)

        if len(closes) > tail_bars:
            closes = closes[-tail_bars:]
            highs = highs[-tail_bars:]
            lows = lows[-tail_bars:]
            timestamps = timestamps[-tail_bars:]

        if timeframe == "DAY":
            closes, highs, lows, timestamps = self._sync_today_daily_candle(
                closes, highs, lows, timestamps
            )

        gc.collect()
        return CandleData(
            closes=closes,
            highs=highs,
            lows=lows,
            timestamps=timestamps,
        )

    def fetch_ltp(self) -> float | None:
        """Fetch last traded price for the configured instrument."""
        cached = self._cached_ltp()
        if cached is not None:
            return cached

        trading = self.config_loader.get_trading_config()
        instrument = self._resolved_instrument()
        symbol = instrument.get("trading_symbol") or str(trading.get("stock_name", ""))
        security_id = str(instrument.get("security_id") or "").strip()
        exchange_segment = str(instrument.get("exchange_segment") or "NSE_EQ")

        if not security_id:
            logger.error("LTP fetch failed for %s — security_id missing", symbol)
            return None

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            payload = {exchange_segment: [int(security_id)]}
            data = None
            for attempt in range(3):
                data = dhan.ticker_data(payload)
                if isinstance(data, dict) and data.get("status") != "failure":
                    price = _extract_last_price(data)
                    if price is not None:
                        return self._cache_ltp(price)
                if attempt < 2:
                    import time

                    time.sleep(0.4 * (attempt + 1))
            logger.error(
                "LTP fetch failed for %s — Dhan API error: %s",
                symbol,
                _format_api_error(data),
            )
        except MemoryError:
            logger.error("LTP fetch failed for %s — MemoryError", symbol)
            gc.collect()
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", symbol, exc)
        return None


def _extract_last_price(payload: Any) -> float | None:
    """Find last_price in Dhan LTP response (SDK or raw REST shapes)."""
    if not isinstance(payload, dict):
        return None
    if "last_price" in payload:
        price = payload["last_price"]
        if isinstance(price, (int, float)) and price > 0:
            return float(price)
    for value in payload.values():
        found = _extract_last_price(value)
        if found is not None:
            return found
    return None


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    """Return the shared market data service."""
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
