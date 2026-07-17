"""Market data via Dhan REST — no Dhan_SRP / pandas on the poll path."""

from __future__ import annotations

import gc
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

try:
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
except ImportError:  # Python < 3.9
    import pytz

    IST = pytz.timezone("Asia/Kolkata")

from core.config_loader import ConfigLoader, get_config_loader
from core.dhan_client import get_dhanhq_lite
from core.logger import get_logger
from core.utils import safe_float

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
    """Normalized OHLC series for Supertrend evaluation."""

    highs: list[float]
    lows: list[float]
    closes: list[float]
    timestamps: list[str]
    last_close: float | None = None
    last_timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.closes:
            self.last_close = self.closes[-1]
        if self.timestamps:
            self.last_timestamp = str(self.timestamps[-1])


def _ist_today() -> date:
    return datetime.now(IST).date()


def _parse_candle_date(timestamp: str) -> date | None:
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


class MarketDataService:
    """Fetches LTPs and OHLC candles via REST (security_id based)."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self._ltp_cache: dict[str, tuple[float, float]] = {}

    def _underlying(self) -> dict[str, Any]:
        return self.config_loader.get_underlying_instrument()

    def _cache_key(self, segment: str, security_id: str) -> str:
        return f"{segment}:{security_id}"

    def _cached_ltp(self, key: str, max_age_seconds: float = 15.0) -> float | None:
        entry = self._ltp_cache.get(key)
        if entry is None:
            return None
        price, cached_at = entry
        if time.monotonic() - cached_at > max_age_seconds:
            return None
        return price

    def _store_ltp(self, key: str, price: float) -> float:
        self._ltp_cache[key] = (price, time.monotonic())
        return price

    def fetch_ltp_by_security_id(
        self,
        security_id: str,
        exchange_segment: str = "NSE_FNO",
        *,
        label: str | None = None,
    ) -> float | None:
        sid = str(security_id or "").strip()
        if not sid:
            logger.error("LTP fetch failed — security_id missing (%s)", label or "")
            return None
        key = self._cache_key(exchange_segment, sid)
        cached = self._cached_ltp(key)
        if cached is not None:
            return cached

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            payload = {exchange_segment: [int(sid)]}
            data = None
            for attempt in range(3):
                data = dhan.ticker_data(payload)
                if isinstance(data, dict) and data.get("status") != "failure":
                    price = _extract_last_price(data)
                    if price is not None:
                        return self._store_ltp(key, price)
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
            logger.error(
                "LTP fetch failed for %s (%s) — Dhan API error: %s",
                label or sid,
                exchange_segment,
                _format_api_error(data),
            )
        except MemoryError:
            logger.error(
                "LTP fetch failed for %s — MemoryError; keep security_id, skip CSV",
                label or sid,
            )
            gc.collect()
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", label or sid, exc)
        return None

    def fetch_spot(self, underlying: str | None = None) -> float | None:
        instrument = self._underlying()
        if underlying and underlying.upper() != str(instrument["symbol"]).upper():
            # Still use configured security_id when symbol matches trading config
            pass
        return self.fetch_ltp_by_security_id(
            str(instrument["security_id"]),
            str(instrument["exchange_segment"]),
            label=str(instrument["symbol"]),
        )

    def fetch_ltp_for_symbol(self, symbol: str) -> float | None:
        """Legacy helper — prefer fetch_ltp_by_security_id for options."""
        _ = symbol
        return self.fetch_spot()

    def fetch_option_ltps(
        self,
        call_security_id: str | None,
        put_security_id: str | None,
        *,
        call_symbol: str | None = None,
        put_symbol: str | None = None,
    ) -> tuple[float | None, float | None]:
        call_ltp = (
            self.fetch_ltp_by_security_id(
                str(call_security_id), "NSE_FNO", label=call_symbol or "CALL"
            )
            if call_security_id
            else None
        )
        put_ltp = (
            self.fetch_ltp_by_security_id(
                str(put_security_id), "NSE_FNO", label=put_symbol or "PUT"
            )
            if put_security_id
            else None
        )
        return call_ltp, put_ltp

    def _parse_ohlc_payload(
        self,
        payload: Any,
        dhan: Any,
    ) -> tuple[list[float], list[float], list[float], list[str]] | None:
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

    def _sync_today_daily_candle(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        timestamps: list[str],
    ) -> tuple[list[float], list[float], list[float], list[str]]:
        ltp = self.fetch_spot()
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

    def fetch_candle_series(
        self,
        underlying: str | None = None,
        timeframe: int | str | None = None,
        min_bars: int | None = None,
    ) -> CandleSeries | None:
        """Fetch OHLC lists for Supertrend (no pandas)."""
        _ = underlying
        st_cfg = self.config_loader.get_supertrend_config()
        length = int(st_cfg.get("length", 10))
        dhan_tf = (
            str(timeframe)
            if timeframe is not None and str(timeframe).upper() == "DAY"
            else None
        )
        if dhan_tf is None and isinstance(timeframe, int):
            dhan_tf = str(timeframe)
        if dhan_tf is None:
            dhan_tf = self.config_loader.get_dhan_timeframe()

        instrument = self._underlying()
        security_id = str(instrument["security_id"])
        exchange_segment = str(instrument["exchange_segment"])
        instrument_type = str(instrument["instrument_name"])
        symbol = str(instrument["symbol"])
        need = min_bars if min_bars is not None else length + 2

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            to_date = _ist_today()
            api_to = (to_date + timedelta(days=1)).isoformat()
            if dhan_tf == "DAY":
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
                interval = int(dhan_tf)
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
                "Failed to fetch candles for %s — MemoryError on low-RAM host",
                symbol,
            )
            gc.collect()
            return None
        except Exception as exc:
            logger.error("Failed to fetch candles for %s: %s", symbol, exc)
            return None

        if not isinstance(response, dict) or response.get("status") == "failure":
            logger.error(
                "Failed to fetch candles for %s — Dhan API error: %s",
                symbol,
                _format_api_error(response),
            )
            return None

        parsed = self._parse_ohlc_payload(response.get("data") or {}, dhan)
        if parsed is None:
            logger.warning("Empty candle data for %s", symbol)
            return None

        closes, highs, lows, timestamps = parsed
        if len(closes) < need:
            logger.warning(
                "Insufficient candles for %s: got %s, need at least %s",
                symbol,
                len(closes),
                need,
            )
            return None

        if dhan_tf == "DAY":
            tail_bars = max(length * 15, 200)
        else:
            tail_bars = max(length * 15, 120)

        if len(closes) > tail_bars:
            closes = closes[-tail_bars:]
            highs = highs[-tail_bars:]
            lows = lows[-tail_bars:]
            timestamps = timestamps[-tail_bars:]

        if dhan_tf == "DAY":
            closes, highs, lows, timestamps = self._sync_today_daily_candle(
                closes, highs, lows, timestamps
            )

        gc.collect()
        return CandleSeries(
            highs=highs, lows=lows, closes=closes, timestamps=timestamps
        )

    def fetch_latest_candle(
        self, underlying: str | None = None, timeframe: int | str | None = None
    ) -> CandleBar | None:
        series = self.fetch_candle_series(underlying, timeframe=timeframe)
        if not series or not series.closes:
            return None
        return CandleBar(
            open=safe_float(series.closes[-1]),
            high=safe_float(series.highs[-1]),
            low=safe_float(series.lows[-1]),
            close=safe_float(series.closes[-1]),
            timestamp=series.last_timestamp,
        )


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
