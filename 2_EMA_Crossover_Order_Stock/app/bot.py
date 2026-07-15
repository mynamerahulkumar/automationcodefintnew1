"""EMA crossover trading bot orchestrator."""

from __future__ import annotations

from app.cli_display import build_poll_summary_log
from app.config_loader import ConfigLoader, get_config_loader
from app.logger import flush_logger, get_logger
from app.market_data import get_market_data_service
from app.order_service import OrderServiceError, get_order_service
from app.scheduler import PollingScheduler
from app.state import get_bot_state
from app.strategy import get_strategy

logger = get_logger()


class TradingBot:
    """Coordinates polling, strategy evaluation, and order execution."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.state = get_bot_state()
        self.market_data = get_market_data_service()
        self.order_service = get_order_service()
        self.strategy = get_strategy(self.config_loader)
        self.scheduler = PollingScheduler(self.config_loader.get_polling_seconds())
        self._rate_limit_backoff = False

    def start(self) -> None:
        """Initialize state and start the polling scheduler."""
        self._sync_state_from_config()
        self.state.set_running()
        self.scheduler.start(self.poll_cycle)
        logger.info("Trading bot started")
        flush_logger()

    def stop(self) -> None:
        """Stop the polling scheduler."""
        self.scheduler.stop()
        self.state.set_stopped()
        logger.info("Trading bot stopped")
        flush_logger()

    def reload(self) -> None:
        """Reload config and refresh strategy/scheduler settings."""
        self.config_loader.reload()
        self.strategy = get_strategy(self.config_loader)
        self.scheduler.update_interval(self.config_loader.get_polling_seconds())
        self._sync_state_from_config()
        logger.info("Trading bot config reloaded")
        flush_logger()

    def _sync_state_from_config(self) -> None:
        trading = self.config_loader.get_trading_config()
        strategy = self.config_loader.get_strategy_config()
        instrument = self.config_loader.get_resolved_instrument()

        self.state.strategy_name = str(strategy.get("name", "EMA_CROSSOVER"))
        self.state.symbol = str(trading.get("stock_name", ""))
        self.state.security_id = str(instrument["security_id"])
        self.state.poll_interval = self.config_loader.get_polling_seconds()

    def _emit_poll_summary(
        self,
        *,
        current_price: float | None,
        fast_ema: float | None,
        slow_ema: float | None,
        signal: str | None,
        candle_time: str | None,
        error: str | None = None,
    ) -> None:
        """Always write a POLL SUMMARY line (success or failure) and flush."""
        strategy_cfg = self.config_loader.get_strategy_config()
        trading = self.config_loader.get_trading_config()
        fast_period = int(strategy_cfg.get("fast_ema", 9))
        slow_period = int(strategy_cfg.get("slow_ema", 21))
        segment = str(trading.get("segment", "EQUITY")).upper()
        symbol = str(trading.get("stock_name", ""))

        self.state.update_poll(
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            signal=signal,
            candle_time=candle_time,
            current_price=current_price,
        )

        summary = build_poll_summary_log(
            symbol=symbol,
            segment=segment,
            fast_period=fast_period,
            slow_period=slow_period,
            current_price=current_price,
            fast_ema=fast_ema,
            slow_ema=slow_ema,
            signal=signal if signal else ("ERROR" if error else None),
            candle_time=candle_time,
        )
        if error:
            logger.warning("%s | Error: %s", summary, error)
        else:
            logger.info(summary)
        flush_logger()

    def poll_cycle(self) -> None:
        """Single poll iteration: fetch data, evaluate, optionally trade."""
        bot_cfg = self.config_loader.get_bot_config()
        cooldown = int(bot_cfg.get("cooldown_seconds", 60))
        one_position_only = bool(bot_cfg.get("one_position_only", True))

        candles = self.market_data.fetch_candles()
        if candles is None:
            # Still try LTP so CLI can show current price even if candles fail
            current_price = self.market_data.fetch_ltp()
            error = "Failed to fetch candle data (check Dhan token / market hours / network)"
            self.state.set_error(error)
            self._emit_poll_summary(
                current_price=current_price,
                fast_ema=None,
                slow_ema=None,
                signal=None,
                candle_time=None,
                error=error,
            )
            return

        result = self.strategy.evaluate(candles)

        current_price = self.market_data.fetch_ltp()
        if current_price is None and candles.last_close is not None:
            current_price = candles.last_close

        self.state.clear_error()
        self._emit_poll_summary(
            current_price=current_price,
            fast_ema=result.fast_ema,
            slow_ema=result.slow_ema,
            signal=result.signal,
            candle_time=result.candle_time,
        )

        if result.signal is None:
            return

        if result.candle_time and self.state.should_skip_signal(
            result.signal, result.candle_time
        ):
            logger.info(
                "Skipping duplicate signal %s for candle %s",
                result.signal,
                result.candle_time,
            )
            flush_logger()
            return

        if self.state.in_cooldown(cooldown):
            logger.info("Skipping %s — cooldown active (%ss)", result.signal, cooldown)
            flush_logger()
            return

        if one_position_only and self.state.should_skip_position(result.signal, True):
            logger.info(
                "Skipping %s — position guard (side=%s)",
                result.signal,
                self.state.position_side,
            )
            flush_logger()
            return

        try:
            order_result = self.order_service.place_signal_order(result.signal)
        except OrderServiceError as exc:
            logger.error("Order failed for signal %s: %s", result.signal, exc.message)
            self.state.set_error(exc.message)
            flush_logger()
            return

        status = order_result.get("status", "")
        if status == "skipped":
            return

        limit_price = float(order_result.get("limit_price", 0) or 0)
        order_id = order_result.get("order_id")
        trade_status = "paper_trade" if status == "paper_trade" else "success"

        self.state.record_trade(
            order_id=order_id,
            side=result.signal,
            price=limit_price,
            status=trade_status,
        )
        self.state.mark_signal_acted(result.signal, result.candle_time)

        logger.info(
            "Signal %s executed: status=%s order_id=%s price=%s",
            result.signal,
            trade_status,
            order_id,
            limit_price,
        )
        flush_logger()


_bot: TradingBot | None = None


def get_trading_bot() -> TradingBot:
    """Return the shared trading bot instance."""
    global _bot
    if _bot is None:
        _bot = TradingBot()
    return _bot
