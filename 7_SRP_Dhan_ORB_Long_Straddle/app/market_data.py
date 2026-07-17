"""Market data via lightweight REST client (no Dhan_SRP / pandas on poll)."""

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

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhanhq_lite
from app.logger import get_logger
from app.utils import INDEX_SECURITY_IDS, safe_float

logger = get_logger()


@dataclass
class CandleBar:
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    timestamp: str | None = None


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


def _extract_ltp_by_security_id(payload: Any, security_id: str) -> float | None:
    """Prefer LTP for a specific security id when multiple are returned."""
    if not isinstance(payload, dict):
        return None
    sid = str(security_id)
    # Nested: data -> SEGMENT -> {sid: {last_price}}
    data = payload.get("data", payload)
    if isinstance(data, dict):
        for segment_payload in data.values():
            if not isinstance(segment_payload, dict):
                continue
            if sid in segment_payload:
                return _extract_last_price(segment_payload[sid])
            # keys may be ints
            for key, value in segment_payload.items():
                if str(key) == sid:
                    return _extract_last_price(value)
    return _extract_last_price(payload)


class MarketDataService:
    """Fetches LTPs and intraday candles for the underlying and option legs."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self._ltp_cache: dict[str, tuple[float, float]] = {}

    def _underlying_security_id(self, underlying: str | None = None) -> str:
        sid = self.config_loader.get_underlying_security_id()
        if sid:
            return sid
        symbol = (underlying or str(self.config_loader.get_trading_config().get("underlying", "NIFTY"))).upper()
        if symbol in INDEX_SECURITY_IDS:
            return str(INDEX_SECURITY_IDS[symbol])
        raise ValueError(f"security.security_id missing for underlying {symbol}")

    def _cache_get(self, key: str, max_age: float = 15.0) -> float | None:
        entry = self._ltp_cache.get(key)
        if not entry:
            return None
        price, cached_at = entry
        if time.monotonic() - cached_at > max_age:
            return None
        return price

    def _cache_set(self, key: str, price: float) -> float:
        self._ltp_cache[key] = (price, time.monotonic())
        return price

    def fetch_spot(self, underlying: str | None = None) -> float | None:
        trading = self.config_loader.get_trading_config()
        symbol = underlying or str(trading.get("underlying", "NIFTY"))
        try:
            security_id = self._underlying_security_id(symbol)
        except ValueError as exc:
            logger.error("%s", exc)
            return None

        cache_key = f"IDX_I:{security_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            payload = {"IDX_I": [int(security_id)]}
            data = None
            for attempt in range(3):
                data = dhan.ticker_data(payload)
                if isinstance(data, dict) and data.get("status") != "failure":
                    price = _extract_ltp_by_security_id(data, security_id)
                    if price is not None:
                        return self._cache_set(cache_key, price)
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
            logger.error(
                "Failed to fetch spot for %s — Dhan API error: %s",
                symbol,
                _format_api_error(data),
            )
        except MemoryError:
            logger.error("Spot LTP fetch failed for %s — MemoryError", symbol)
            gc.collect()
        except Exception as exc:
            logger.error("Spot LTP fetch failed for %s: %s", symbol, exc)
        return None

    def fetch_ltp_for_symbol(self, symbol: str) -> float | None:
        """Legacy helper — prefer security-id based fetch for options."""
        # Without security id we cannot use REST ticker reliably by symbol alone.
        logger.warning("fetch_ltp_for_symbol(%s) called without security_id; returning None", symbol)
        return None

    def fetch_ltp_by_security_id(
        self,
        security_id: str,
        exchange_segment: str = "NSE_FNO",
    ) -> float | None:
        sid = str(security_id).strip()
        if not sid:
            return None
        cache_key = f"{exchange_segment}:{sid}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            payload = {exchange_segment: [int(sid)]}
            data = None
            for attempt in range(3):
                data = dhan.ticker_data(payload)
                if isinstance(data, dict) and data.get("status") != "failure":
                    price = _extract_ltp_by_security_id(data, sid)
                    if price is not None:
                        return self._cache_set(cache_key, price)
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
            logger.error(
                "LTP fetch failed for sid=%s — Dhan API error: %s",
                sid,
                _format_api_error(data),
            )
        except MemoryError:
            logger.error("LTP fetch failed for sid=%s — MemoryError", sid)
            gc.collect()
        except Exception as exc:
            logger.error("LTP fetch failed for sid=%s: %s", sid, exc)
        return None

    def fetch_option_ltps(
        self,
        call_security_id: str | None,
        put_security_id: str | None,
        exchange_segment: str = "NSE_FNO",
    ) -> tuple[float | None, float | None]:
        ids = [int(x) for x in (call_security_id, put_security_id) if x]
        if not ids:
            return None, None

        # Use cache when both present and fresh
        call_ltp = (
            self._cache_get(f"{exchange_segment}:{call_security_id}")
            if call_security_id
            else None
        )
        put_ltp = (
            self._cache_get(f"{exchange_segment}:{put_security_id}")
            if put_security_id
            else None
        )
        if (not call_security_id or call_ltp is not None) and (
            not put_security_id or put_ltp is not None
        ):
            return call_ltp, put_ltp

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            data = None
            for attempt in range(3):
                data = dhan.ticker_data({exchange_segment: ids})
                if isinstance(data, dict) and data.get("status") != "failure":
                    if call_security_id:
                        call_ltp = _extract_ltp_by_security_id(data, str(call_security_id))
                        if call_ltp is not None:
                            self._cache_set(f"{exchange_segment}:{call_security_id}", call_ltp)
                    if put_security_id:
                        put_ltp = _extract_ltp_by_security_id(data, str(put_security_id))
                        if put_ltp is not None:
                            self._cache_set(f"{exchange_segment}:{put_security_id}", put_ltp)
                    if (not call_security_id or call_ltp is not None) or (
                        not put_security_id or put_ltp is not None
                    ):
                        return call_ltp, put_ltp
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
            logger.error(
                "Option LTP fetch failed — Dhan API error: %s",
                _format_api_error(data),
            )
        except MemoryError:
            logger.error("Option LTP fetch failed — MemoryError")
            gc.collect()
        except Exception as exc:
            logger.error("Option LTP fetch failed: %s", exc)
        return call_ltp, put_ltp

    def _parse_ohlc_payload(
        self,
        payload: Any,
        dhan: Any,
    ) -> list[dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None
        closes_raw = payload.get("close")
        if closes_raw is None:
            return None
        opens_raw = payload.get("open", closes_raw)
        highs_raw = payload.get("high", closes_raw)
        lows_raw = payload.get("low", closes_raw)
        ts_raw = payload.get("timestamp", [])

        bars: list[dict[str, Any]] = []
        for i, close in enumerate(closes_raw):
            ts = ts_raw[i] if i < len(ts_raw) else i
            try:
                ts_str = str(dhan.convert_to_date_time(ts))
            except Exception:
                ts_str = str(ts)
            bars.append(
                {
                    "open": float(opens_raw[i]),
                    "high": float(highs_raw[i]),
                    "low": float(lows_raw[i]),
                    "close": float(close),
                    "timestamp": ts_str,
                }
            )
        return bars or None

    def fetch_latest_candle(
        self,
        underlying: str | None = None,
        timeframe: int = 5,
    ) -> CandleBar | None:
        trading = self.config_loader.get_trading_config()
        symbol = underlying or str(trading.get("underlying", "NIFTY"))
        tf = timeframe if timeframe in {1, 2, 3, 5, 10, 15, 30, 60} else 5
        try:
            security_id = self._underlying_security_id(symbol)
        except ValueError as exc:
            logger.error("%s", exc)
            return None

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            today = _ist_today()
            from_date = (today - timedelta(days=2)).isoformat()
            to_date = (today + timedelta(days=1)).isoformat()
            response = dhan.intraday_minute_data(
                security_id,
                "IDX_I",
                "INDEX",
                from_date,
                to_date,
                interval=tf,
            )
        except MemoryError:
            logger.error("Intraday candle fetch failed for %s — MemoryError", symbol)
            gc.collect()
            return None
        except Exception as exc:
            logger.error("Intraday candle fetch failed for %s: %s", symbol, exc)
            return None

        if not isinstance(response, dict) or response.get("status") == "failure":
            logger.error(
                "Intraday candle fetch failed for %s — Dhan API error: %s",
                symbol,
                _format_api_error(response),
            )
            return None

        bars = self._parse_ohlc_payload(response.get("data") or {}, dhan)
        gc.collect()
        if not bars:
            return None
        row = bars[-1]
        return CandleBar(
            open=safe_float(row["open"]),
            high=safe_float(row["high"]),
            low=safe_float(row["low"]),
            close=safe_float(row["close"]),
            timestamp=str(row["timestamp"]),
        )

    def fetch_opening_range(
        self,
        underlying: str,
        opening_range_minutes: int,
        bar_minutes: int = 5,
    ) -> tuple[float | None, float | None]:
        """Compute ORB high/low from first N intraday bars covering the opening window."""
        tf = bar_minutes if bar_minutes in {1, 2, 3, 5, 10, 15, 30, 60} else 5
        try:
            security_id = self._underlying_security_id(underlying)
        except ValueError as exc:
            logger.error("%s", exc)
            return None, None

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            today = _ist_today()
            from_date = today.isoformat()
            to_date = (today + timedelta(days=1)).isoformat()
            response = dhan.intraday_minute_data(
                security_id,
                "IDX_I",
                "INDEX",
                from_date,
                to_date,
                interval=tf,
            )
        except MemoryError:
            logger.error("ORB candle fetch failed — MemoryError")
            gc.collect()
            return None, None
        except Exception as exc:
            logger.error("ORB candle fetch failed: %s", exc)
            return None, None

        if not isinstance(response, dict) or response.get("status") == "failure":
            logger.error(
                "ORB candle fetch failed — Dhan API error: %s",
                _format_api_error(response),
            )
            return None, None

        bars = self._parse_ohlc_payload(response.get("data") or {}, dhan)
        gc.collect()
        if not bars:
            return None, None

        n = max(1, int(opening_range_minutes / tf))
        window = bars[:n]
        try:
            high = max(float(b["high"]) for b in window)
            low = min(float(b["low"]) for b in window)
            return high, low
        except Exception as exc:
            logger.error("ORB high/low computation failed: %s", exc)
            return None, None


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
