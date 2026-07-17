"""Market data via lightweight REST (no dhanhq / pandas on poll path)."""

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

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhanhq_lite
from app.logger import get_logger
from app.utils import INDEX_SECURITY_IDS

logger = get_logger()

INDEX_EXCHANGE_SEGMENT = {
    "NIFTY": "IDX_I",
    "BANKNIFTY": "IDX_I",
    "FINNIFTY": "IDX_I",
    "MIDCPNIFTY": "IDX_I",
    "SENSEX": "IDX_I",
    "BANKEX": "IDX_I",
}


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
    highs: list[float] | None = None
    lows: list[float] | None = None
    last_close: float | None = None
    last_timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.closes:
            self.last_close = self.closes[-1]
        if self.timestamps:
            self.last_timestamp = str(self.timestamps[-1])


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
    """Fetches LTPs and candles for the underlying and option legs via REST."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self._ltp_cache: dict[str, tuple[float, float]] = {}

    def resolve_underlying(self, underlying: str | None = None) -> dict[str, str]:
        trading = self.config_loader.get_trading_config()
        security = self.config_loader.get_security_config()
        symbol = (underlying or str(trading.get("underlying", "NIFTY"))).upper()
        security_id = str(security.get("security_id") or "").strip()
        if not security_id and symbol in INDEX_SECURITY_IDS:
            security_id = str(INDEX_SECURITY_IDS[symbol])
        exchange = str(trading.get("exchange", "NSE")).upper()
        if symbol in INDEX_EXCHANGE_SEGMENT:
            segment = INDEX_EXCHANGE_SEGMENT[symbol]
            instrument = "INDEX"
        else:
            segment = "NSE_EQ" if exchange == "NSE" else "BSE_EQ"
            instrument = "EQUITY"
        return {
            "symbol": symbol,
            "security_id": security_id,
            "exchange_segment": segment,
            "instrument": instrument,
        }

    def fetch_spot(self, underlying: str | None = None) -> float | None:
        info = self.resolve_underlying(underlying)
        return self._fetch_ltp_by_id(
            info["security_id"],
            info["exchange_segment"],
            label=info["symbol"],
        )

    def fetch_ltp_for_symbol(self, symbol: str) -> float | None:
        """Fallback: try underlying resolver; otherwise return None (use security_id path)."""
        info = self.resolve_underlying(symbol)
        if info["security_id"]:
            return self._fetch_ltp_by_id(
                info["security_id"],
                info["exchange_segment"],
                label=symbol,
            )
        return None

    def fetch_ltp_by_security_id(
        self,
        security_id: str | None,
        exchange_segment: str = "NSE_FNO",
        *,
        label: str | None = None,
    ) -> float | None:
        return self._fetch_ltp_by_id(
            str(security_id or ""),
            exchange_segment,
            label=label,
        )

    def fetch_option_ltps(
        self,
        call_symbol: str | None,
        put_symbol: str | None,
        *,
        call_security_id: str | None = None,
        put_security_id: str | None = None,
    ) -> tuple[float | None, float | None]:
        """Fetch CE/PE LTPs via REST using security ids when available."""
        call_ltp = put_ltp = None
        if call_security_id:
            call_ltp = self._fetch_ltp_by_id(str(call_security_id), "NSE_FNO", label=call_symbol)
        if put_security_id:
            put_ltp = self._fetch_ltp_by_id(str(put_security_id), "NSE_FNO", label=put_symbol)
        return call_ltp, put_ltp

    def fetch_latest_candle(
        self,
        underlying: str | None = None,
        timeframe: int | None = None,
    ) -> CandleBar | None:
        series = self.fetch_candle_series(underlying, timeframe=timeframe)
        if not series or not series.closes:
            return None
        close = series.closes[-1]
        high = series.highs[-1] if series.highs else close
        low = series.lows[-1] if series.lows else close
        return CandleBar(
            open=close,
            high=high,
            low=low,
            close=close,
            timestamp=series.last_timestamp,
        )

    def fetch_candle_series(
        self,
        underlying: str | None = None,
        timeframe: int | None = None,
        min_bars: int | None = None,
    ) -> CandleSeries | None:
        """Fetch close series for EMA (REST only, no pandas)."""
        ema_cfg = self.config_loader.get_ema_config()
        info = self.resolve_underlying(underlying)
        symbol = info["symbol"]
        security_id = info["security_id"]
        if not security_id:
            logger.error(
                "Failed to fetch candles for %s — security_id missing in config",
                symbol,
            )
            return None

        dhan_tf = self.config_loader.get_dhan_timeframe()
        if timeframe is not None and dhan_tf != "DAY":
            # Allow explicit minute override from caller when not daily.
            if timeframe in {1, 5, 15, 25, 60}:
                dhan_tf = str(timeframe)

        slow = int(ema_cfg.get("slow", 21))
        need = min_bars if min_bars is not None else (
            max(slow * 15, 200) if dhan_tf == "DAY" else max(slow * 10, 120)
        )

        try:
            dhan = get_dhanhq_lite(self.config_loader)
            to_date = _ist_today()
            api_to = (to_date + timedelta(days=1)).isoformat()
            if dhan_tf == "DAY":
                from_date = to_date - timedelta(days=400)
                response = dhan.historical_daily_data(
                    security_id,
                    info["exchange_segment"],
                    info["instrument"],
                    from_date.isoformat(),
                    api_to,
                    0,
                )
            else:
                interval = int(dhan_tf)
                from_date = to_date - timedelta(days=5)
                response = dhan.intraday_minute_data(
                    security_id,
                    info["exchange_segment"],
                    info["instrument"],
                    from_date.isoformat(),
                    api_to,
                    interval,
                )
        except MemoryError:
            logger.error(
                "Failed to fetch candles for %s — MemoryError on low-RAM host; "
                "keep security_id set and avoid loading CSV on poll",
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
        min_needed = slow + 2
        if len(closes) < min_needed:
            logger.warning(
                "Insufficient candles for %s: got %s, need at least %s",
                symbol,
                len(closes),
                min_needed,
            )
            return None

        if len(closes) > need:
            closes = closes[-need:]
            highs = highs[-need:]
            lows = lows[-need:]
            timestamps = timestamps[-need:]

        if dhan_tf == "DAY":
            closes, highs, lows, timestamps = self._sync_today_daily_candle(
                closes, highs, lows, timestamps, symbol=symbol
            )

        gc.collect()
        return CandleSeries(
            closes=closes,
            timestamps=timestamps,
            highs=highs,
            lows=lows,
        )

    def _sync_today_daily_candle(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        timestamps: list[str],
        *,
        symbol: str,
    ) -> tuple[list[float], list[float], list[float], list[str]]:
        ltp = self.fetch_spot(symbol)
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

    def _cached_ltp(self, key: str, max_age: float = 15.0) -> float | None:
        import time

        cached = self._ltp_cache.get(key)
        if not cached:
            return None
        price, at = cached
        if time.monotonic() - at > max_age:
            return None
        return price

    def _store_ltp(self, key: str, price: float) -> float:
        import time

        self._ltp_cache[key] = (price, time.monotonic())
        return price

    def _fetch_ltp_by_id(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        label: str | None = None,
    ) -> float | None:
        sid = str(security_id or "").strip()
        if not sid:
            logger.error("LTP fetch failed for %s — security_id missing", label or "?")
            return None

        cache_key = f"{exchange_segment}:{sid}"
        cached = self._cached_ltp(cache_key)
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
                        return self._store_ltp(cache_key, price)
                if attempt < 2:
                    import time

                    time.sleep(0.4 * (attempt + 1))
            logger.error(
                "LTP fetch failed for %s — Dhan API error: %s",
                label or sid,
                _format_api_error(data),
            )
        except MemoryError:
            logger.error("LTP fetch failed for %s — MemoryError", label or sid)
            gc.collect()
        except Exception as exc:
            logger.error("LTP fetch failed for %s: %s", label or sid, exc)
        return None


_market_data_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    global _market_data_service
    if _market_data_service is None:
        _market_data_service = MarketDataService()
    return _market_data_service
