"""Long Straddle ORB trading bot orchestrator."""

from __future__ import annotations

import time
from datetime import timedelta

from app.cli_display import build_poll_dashboard, build_poll_summary_log
from app.config_loader import ConfigLoader, get_config_loader
from app.logger import get_logger
from app.market_data import get_market_data_service
from app.order_service import OrderServiceError, get_order_service
from app.scheduler import PollingScheduler
from app.state import get_bot_state
from app.strategy import get_strategy
from app.utils import now_ist

logger = get_logger()


class TradingBot:
    """Coordinates polling, strategy evaluation, and dual-leg order execution."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.state = get_bot_state()
        self.market_data = get_market_data_service()
        self.order_service = get_order_service()
        self.strategy = get_strategy(self.config_loader)
        self.scheduler = PollingScheduler(self.config_loader.get_polling_seconds())

    def start(self) -> None:
        self._sync_state_from_config()
        self.state.set_running()
        if self.config_loader.get_bot_config().get("enabled", True):
            self.scheduler.start(self.poll_cycle)
            logger.info("Trading bot started")
        else:
            logger.warning("Bot disabled in config — FastAPI only")

    def stop(self) -> None:
        self.state.manual_stop_requested = True
        try:
            if self.state.entry_done and not self.state.square_off_done:
                self.order_service.exit_all_open(reason="manual_stop")
        except Exception:
            logger.exception("Square-off during stop failed")
        self.scheduler.stop()
        self.state.set_stopped()
        logger.info("Trading bot stopped")

    def reload(self) -> None:
        self.config_loader.reload()
        self.strategy = get_strategy(self.config_loader)
        self.scheduler.update_interval(self.config_loader.get_polling_seconds())
        self._sync_state_from_config()
        logger.info("Trading bot config reloaded")

    def _sync_state_from_config(self) -> None:
        trading = self.config_loader.get_trading_config()
        strategy = self.config_loader.get_strategy_config()
        self.state.strategy_name = str(strategy.get("name", "Long Straddle ORB"))
        self.state.underlying = str(trading.get("underlying", ""))
        self.state.poll_interval = self.config_loader.get_polling_seconds()

    def poll_cycle(self) -> None:
        started = time.perf_counter()
        now = now_ist()
        self.state.reset_session_if_needed(now.strftime("%Y-%m-%d"))

        trading = self.config_loader.get_trading_config()
        strategy_cfg = self.config_loader.get_strategy_config()
        underlying = str(trading.get("underlying", "NIFTY"))
        orb_minutes = int(strategy_cfg.get("opening_range_minutes", 15))

        spot = self.market_data.fetch_spot(underlying)
        self.state.spot_price = spot

        candle = self.market_data.fetch_latest_candle(underlying, timeframe=5)
        if candle:
            self.state.candle.open = candle.open
            self.state.candle.high = candle.high
            self.state.candle.low = candle.low
            self.state.candle.close = candle.close
            self.state.candle.timestamp = candle.timestamp
            if spot is None and candle.close is not None:
                spot = candle.close
                self.state.spot_price = spot

        call_ltp = put_ltp = None
        if self.state.call.security_id or self.state.put.security_id:
            call_ltp, put_ltp = self.market_data.fetch_option_ltps(
                self.state.call.security_id,
                self.state.put.security_id,
            )
            self._update_leg_mark(self.state.call, call_ltp)
            self._update_leg_mark(self.state.put, put_ltp)
            if self.state.call.status == "TRAILING" and call_ltp is not None:
                self.order_service.update_trailing("CALL", call_ltp)
            if self.state.put.status == "TRAILING" and put_ltp is not None:
                self.order_service.update_trailing("PUT", put_ltp)

        decision = self.strategy.evaluate(
            self.state,
            now=now,
            spot=spot,
            call_ltp=call_ltp,
            put_ltp=put_ltp,
        )
        self.state.breakout_status = decision.breakout_status

        try:
            self._execute_decision(decision, underlying=underlying, orb_minutes=orb_minutes, spot=spot)
            self.state.clear_error()
        except OrderServiceError as exc:
            logger.error("Order error: %s", exc.message)
            self.state.set_error(exc.message)
        except Exception as exc:
            logger.error(
                "Unhandled error in poll cycle: %s: %s",
                type(exc).__name__,
                exc,
            )
            self.state.set_error(f"{type(exc).__name__}: {exc}")

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        next_poll = (now + timedelta(seconds=self.state.poll_interval)).isoformat()
        self.state.update_poll_meta(api_response_ms=round(elapsed_ms, 1), next_poll_at=next_poll)
        self._refresh_combined_pnl()

        snapshot = self.state.snapshot()
        logger.info(build_poll_summary_log(snapshot))

        bot_cfg = self.config_loader.get_bot_config()
        always = bool(bot_cfg.get("always_refresh_cli", True))
        every = int(bot_cfg.get("cli_refresh_every", 3))
        if always or (every > 0 and self.state.poll_count % every == 0):
            # Structured marker for start.py / logs.py CLI rendering
            logger.info("CLI DASHBOARD\n%s", build_poll_dashboard(snapshot))

    def _execute_decision(
        self,
        decision,
        *,
        underlying: str,
        orb_minutes: int,
        spot: float | None,
    ) -> None:
        action = decision.action

        if action == "WAIT":
            self.state.phase = self.state.PHASE_WAITING
            return

        if action == "ENTER":
            logger.info("Entry signal: %s", decision.reason)
            self.order_service.enter_straddle()
            # Seed ORB with current spot
            if spot is not None:
                self.state.orb_high = spot
                self.state.orb_low = spot
            return

        if action == "UPDATE_ORB":
            self.state.phase = self.state.PHASE_BUILDING_ORB
            if spot is not None:
                self.state.orb_high = max(self.state.orb_high or spot, spot)
                self.state.orb_low = min(self.state.orb_low or spot, spot)
            if decision.reason == "finalize_opening_range":
                high, low = self.market_data.fetch_opening_range(underlying, orb_minutes)
                if high is not None and low is not None:
                    self.state.orb_high = high
                    self.state.orb_low = low
                self.state.orb_complete = True
                self.state.phase = self.state.PHASE_MONITORING
                logger.info(
                    "ORB finalized high=%s low=%s",
                    self.state.orb_high,
                    self.state.orb_low,
                )
            return

        if action == "BREAKOUT_UP":
            logger.info("Breakout UP — exit PUT, trail CALL")
            self.order_service.exit_leg("PUT", decision.reason)
            self.order_service.enable_trailing("CALL")
            self.state.breakout_done = True
            self.state.phase = self.state.PHASE_CALL_ONLY
            self.state.breakout_status = "Above High"
            return

        if action == "BREAKOUT_DOWN":
            logger.info("Breakout DOWN — exit CALL, trail PUT")
            self.order_service.exit_leg("CALL", decision.reason)
            self.order_service.enable_trailing("PUT")
            self.state.breakout_done = True
            self.state.phase = self.state.PHASE_PUT_ONLY
            self.state.breakout_status = "Below Low"
            return

        if action == "EXIT_CALL":
            self.order_service.exit_leg("CALL", decision.reason)
            if self.state.put.status not in {"OPEN", "TRAILING"}:
                self.state.phase = self.state.PHASE_FLAT
                self.state.square_off_done = True
            return

        if action == "EXIT_PUT":
            self.order_service.exit_leg("PUT", decision.reason)
            if self.state.call.status not in {"OPEN", "TRAILING"}:
                self.state.phase = self.state.PHASE_FLAT
                self.state.square_off_done = True
            return

        if action == "EXIT_ALL":
            self.order_service.exit_all_open(reason=decision.reason)
            return

    @staticmethod
    def _update_leg_mark(leg, ltp: float | None) -> None:
        if ltp is None or leg.status not in {"OPEN", "TRAILING"}:
            return
        leg.current_price = ltp
        if leg.entry_price is not None:
            leg.pnl = (ltp - leg.entry_price) * leg.quantity

    def _refresh_combined_pnl(self) -> None:
        parts = []
        for leg in (self.state.call, self.state.put):
            if leg.pnl is not None:
                parts.append(leg.pnl)
        self.state.combined_pnl = sum(parts) if parts else None


_trading_bot: TradingBot | None = None


def get_trading_bot() -> TradingBot:
    global _trading_bot
    if _trading_bot is None:
        _trading_bot = TradingBot()
    return _trading_bot
