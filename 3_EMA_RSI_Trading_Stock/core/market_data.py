"""Market data fetching via Dhan_SRP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from core.config_loader import ConfigLoader, get_config_loader, resolve_instrument
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


def _parse_candle_date(timestamp: str) -> date | None:
    """Extract calendar date from a candle timestamp string."""
    text = str(timestamp).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 else text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


class MarketDataService:
    """Fetches OHLCV candles and LTP for the configured instrument."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def _resolved_instrument(self) -> dict:
        try:
            return self.config_loader.get_resolved_instrument()
        except Exception:
            try:
                return resolve_instrument(self.config_loader.get_market_config())
            except Exception:
                return {}

    def _sync_today_daily_candle(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        timestamps: list[str],
    ) -> tuple[list[float], list[float], list[float], list[str]]:
        """
        Dhan daily history often omits the current session bar.

        Merge LTP into today's daily candle so EMA/RSI match live charts.
        """
        ltp = self.fetch_ltp()
        if ltp is None or ltp <= 0 or not timestamps:
            return closes, highs, lows, timestamps

        today = date.today()
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

    def fetch_candles(self) -> CandleData | None:
        """Fetch historical candles for strategy evaluation."""
        trading = self.config_loader.get_trading_config()
        ema = self.config_loader.get_ema_config()
        rsi = self.config_loader.get_rsi_config()

        stock_name = str(trading.get("stock_name", ""))
        exchange = str(trading.get("exchange", "NSE"))
        timeframe = self.config_loader.get_dhan_timeframe()
        slow_ema = int(ema.get("slow", 21))
        rsi_period = int(rsi.get("period", 14))
        min_bars_needed = max(slow_ema, rsi_period) + 2

        instrument = self._resolved_instrument()
        security_id = str(instrument.get("security_id") or "").strip() or None
        instrument_type = str(instrument.get("instrument_name") or "EQUITY")

        dhan = get_dhan_client(self.config_loader)

        try:
            df = dhan.get_historical_data(
                stock_name,
                exchange,
                timeframe,
                security_id=security_id,
                instrument_type=instrument_type,
            )
        except Exception as exc:
            logger.error("Failed to fetch candles for %s: %s", stock_name, exc)
            return None

        # Dhan_SRP swallows API errors and returns None — surface that clearly.
        if df is None:
            logger.error(
                "Failed to fetch candles for %s — Dhan API returned no data "
                "(check access token and Data API subscription)",
                stock_name,
            )
            return None

        if getattr(df, "empty", True):
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

        # Long lookback so EMA/RSI converge toward chart platforms (TradingView).
        # Daily needs more history; intraday keeps a lighter window.
        if timeframe == "DAY":
            tail_bars = max(slow_ema * 20, rsi_period * 20, 250)
        else:
            tail_bars = max(slow_ema * 15, rsi_period * 15, 150)
        tail = df.tail(tail_bars)

        closes = [float(x) for x in tail["close"].tolist()]
        highs = [float(x) for x in tail.get("high", tail["close"]).tolist()]
        lows = [float(x) for x in tail.get("low", tail["close"]).tolist()]
        timestamps = [str(x) for x in tail["timestamp"].tolist()]

        if timeframe == "DAY":
            closes, highs, lows, timestamps = self._sync_today_daily_candle(
                closes, highs, lows, timestamps
            )

        return CandleData(
            closes=closes,
            highs=highs,
            lows=lows,
            timestamps=timestamps,
        )

    def fetch_ltp(self) -> float | None:
        """Fetch last traded price for the configured instrument."""
        trading = self.config_loader.get_trading_config()
        instrument = self._resolved_instrument()
        symbol = instrument.get("trading_symbol") or str(trading.get("stock_name", ""))
        security_id = str(instrument.get("security_id") or "").strip()
        exchange_segment = str(instrument.get("exchange_segment") or "NSE_EQ")

        try:
            dhan = get_dhan_client(self.config_loader)
            # Prefer security_id path so we never need the full instrument CSV for LTP.
            if security_id:
                payload = {exchange_segment: [int(security_id)]}
                data = dhan.Dhan.ticker_data(payload)
                if isinstance(data, dict) and data.get("status") != "failure":
                    nested = (data.get("data") or {}).get("data") or {}
                    for segment_data in nested.values():
                        if not isinstance(segment_data, dict):
                            continue
                        for values in segment_data.values():
                            if isinstance(values, dict) and "last_price" in values:
                                price = values["last_price"]
                                if isinstance(price, (int, float)) and price > 0:
                                    return float(price)

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
