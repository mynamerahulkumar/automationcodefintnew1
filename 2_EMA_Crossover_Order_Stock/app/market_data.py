"""Market data fetching via Dhan SDK security_id path (low memory)."""

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


@dataclass
class CandleFetchResult:
    """Candle fetch outcome with a human-readable error if failed."""

    candles: CandleData | None
    error: str | None = None


def _format_dhan_failure(response: dict | None) -> str:
    """Extract a short actionable message from a Dhan API failure payload."""
    if not isinstance(response, dict):
        return f"Unexpected Dhan response: {response!r}"

    remarks = response.get("remarks")
    data = response.get("data")
    parts: list[str] = []

    if isinstance(remarks, dict):
        for key in ("error_message", "error_code", "error_type", "message"):
            val = remarks.get(key)
            if val not in (None, ""):
                parts.append(f"{key}={val}")
        if not parts:
            parts.append(str(remarks))
    elif remarks not in (None, ""):
        parts.append(str(remarks))

    if data not in (None, "", {}):
        parts.append(f"data={data}")

    text = "; ".join(parts) if parts else str(response)
    lower = text.lower()
    if "invalid ip" in lower or "dh-905" in lower or "ip" in lower and "whitelist" in lower:
        return (
            f"{text} | ACTION: Whitelist this AWS public IP in Dhan → "
            "My Profile → Access → API → IP Whitelist"
        )
    if "token" in lower or "auth" in lower or "unauthorized" in lower or "401" in lower:
        return f"{text} | ACTION: Refresh DHAN_ACCESS_TOKEN in .env on the AWS server"
    if not text or text in ("{'error_code': None, 'error_type': None, 'error_message': None}",):
        return (
            "Dhan returned empty failure (often Invalid IP / expired token / no Data API access). "
            "Whitelist AWS public IP in Dhan and verify .env token."
        )
    return text


class MarketDataService:
    """Fetches OHLCV candles for strategy evaluation."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.last_error: str | None = None

    def _resolved(self) -> dict:
        return resolve_instrument(self.config_loader.get_trading_config())

    def fetch_candles(self) -> CandleData | None:
        """Backward-compatible wrapper — prefer fetch_candles_result()."""
        return self.fetch_candles_result().candles

    def fetch_candles_result(self) -> CandleFetchResult:
        """Fetch intraday candles; always return structured success/error."""
        self.last_error = None
        trading = self.config_loader.get_trading_config()
        strategy = self.config_loader.get_strategy_config()
        stock_name = str(trading.get("stock_name", ""))
        timeframe = self.config_loader.parse_timeframe_minutes()
        slow_ema = int(strategy.get("slow_ema", 21))

        if timeframe not in VALID_INTERVALS:
            err = f"Unsupported timeframe minutes={timeframe} (allowed {sorted(VALID_INTERVALS)})"
            self.last_error = err
            logger.error(err)
            return CandleFetchResult(None, err)

        try:
            instrument = self._resolved()
        except (ValueError, FileNotFoundError) as exc:
            err = f"Instrument resolve failed: {exc}"
            self.last_error = err
            logger.error(err)
            return CandleFetchResult(None, err)

        security_id = str(instrument["security_id"])
        exchange_segment = str(instrument["exchange_segment"])
        instrument_type = str(instrument.get("instrument_name") or "EQUITY")

        # Prefer Dhan SDK constants when available (same values Dhan_SRP uses)
        try:
            dhan = get_dhan_client(self.config_loader)
            sdk_seg = getattr(dhan.Dhan, "NSE", None) if exchange_segment == "NSE_EQ" else None
            if exchange_segment == "BSE_EQ":
                sdk_seg = getattr(dhan.Dhan, "BSE", None)
            if sdk_seg:
                exchange_segment = sdk_seg
        except Exception as exc:
            err = f"Dhan client init failed: {exc}"
            self.last_error = err
            logger.error(err)
            flush_logger()
            return CandleFetchResult(None, err)

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
            response = dhan.Dhan.intraday_minute_data(
                security_id=security_id,
                exchange_segment=exchange_segment,
                instrument_type=instrument_type,
                from_date=from_date,
                to_date=to_date,
                interval=int(timeframe),
            )
        except Exception as exc:
            err = f"Candle API exception: {exc}"
            self.last_error = err
            logger.error(err)
            flush_logger()
            return CandleFetchResult(None, err)

        if not isinstance(response, dict) or response.get("status") == "failure":
            err = _format_dhan_failure(response if isinstance(response, dict) else None)
            self.last_error = err
            logger.error("Candle API failure for %s: %s", stock_name, response)
            flush_logger()
            return CandleFetchResult(None, err)

        data = response.get("data")
        if not data:
            err = _format_dhan_failure(response)
            if "empty" not in err.lower():
                err = f"Empty candle payload from Dhan. {err}"
            self.last_error = err
            logger.warning("Empty candle payload for %s: %s", stock_name, response)
            flush_logger()
            return CandleFetchResult(None, err)

        try:
            df = pd.DataFrame(data)
        except Exception as exc:
            err = f"Could not parse candle data: {exc}"
            self.last_error = err
            logger.error(err)
            return CandleFetchResult(None, err)

        if df.empty or "close" not in df.columns:
            err = f"No close prices in candle data (cols={list(df.columns)})"
            self.last_error = err
            logger.warning(err)
            return CandleFetchResult(None, err)

        if "timestamp" in df.columns:
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(
                    "Asia/Kolkata"
                )
            except Exception:
                df["timestamp"] = df["timestamp"].astype(str)

        if len(df) < slow_ema + 2:
            err = f"Insufficient candles: got {len(df)}, need at least {slow_ema + 2}"
            self.last_error = err
            logger.warning(err)
            return CandleFetchResult(None, err)

        min_bars = max(slow_ema * 3, 60)
        tail = df.tail(min_bars)
        closes = [float(x) for x in tail["close"].tolist()]
        if "timestamp" in tail.columns:
            timestamps = [str(x) for x in tail["timestamp"].tolist()]
        else:
            timestamps = [str(i) for i in range(len(closes))]

        logger.info("Candles ready for %s: %s bars, last_close=%s", stock_name, len(closes), closes[-1])
        flush_logger()
        return CandleFetchResult(CandleData(closes=closes, timestamps=timestamps), None)

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
            # Map to SDK segment constant if present
            if exchange_segment == "NSE_EQ" and getattr(sdk, "NSE", None):
                exchange_segment = sdk.NSE
            payload = {exchange_segment: [int(security_id)]}

            for method_name in ("ohlc_data", "quote_data", "ticker_data"):
                fn = getattr(sdk, method_name, None)
                if not callable(fn):
                    continue
                try:
                    raw = fn(payload)
                    if isinstance(raw, dict) and raw.get("status") == "failure":
                        logger.warning("%s failure: %s", method_name, _format_dhan_failure(raw))
                        continue
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
