"""Long Straddle Supertrend Confirmation trading bot orchestrator."""

from __future__ import annotations

import time
from datetime import timedelta

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

from core.cli import build_poll_dashboard, build_poll_summary_log
from core.config_loader import ConfigLoader, get_config_loader
from core.logger import get_logger
from core.market_data import get_market_data_service
from core.order_manager import OrderManagerError, get_order_manager
from core.position_manager import get_bot_state
from core.scheduler import PollingScheduler
from core.utils import now_ist
from indicator.supertrend import SupertrendEngine
from strategy import get_strategy

logger = get_logger()


class TradingBot:
    """Coordinates polling, Supertrend confirmation, and dual-leg order execution."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.state = get_bot_state()
        self.market_data = get_market_data_service()
        self.order_manager = get_order_manager()
        self.strategy = get_strategy(self.config_loader)
        self.scheduler = PollingScheduler(self.config_loader.get_polling_seconds())
        self._st_engine = self._build_supertrend_engine()

    def _build_supertrend_engine(self) -> SupertrendEngine:
        st_cfg = self.config_loader.get_supertrend_config()
        return SupertrendEngine(
            length=int(st_cfg.get("length", 10)),
            multiplier=float(st_cfg.get("multiplier", 3)),
        )

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
                self.order_manager.exit_all_open(reason="manual_stop")
        except Exception:
            logger.exception("Square-off during stop failed")
        self.scheduler.stop()
        self.state.set_stopped()
        logger.info("Trading bot stopped")

    def reload(self) -> None:
        self.config_loader.reload()
        self.strategy = get_strategy(self.config_loader)
        self._st_engine = self._build_supertrend_engine()
        self.scheduler.update_interval(self.config_loader.get_polling_seconds())
        self._sync_state_from_config()
        logger.info("Trading bot config reloaded")

    def _sync_state_from_config(self) -> None:
        trading = self.config_loader.get_trading_config()
        strategy = self.config_loader.get_strategy_config()
        self.state.strategy_name = str(
            strategy.get("name", "Long Straddle Supertrend Confirmation")
        )
        self.state.underlying = str(trading.get("underlying", ""))
        self.state.poll_interval = self.config_loader.get_polling_seconds()

    def poll_cycle(self) -> None:
        started = time.perf_counter()
        now = now_ist()
        self.state.reset_session_if_needed(now.strftime("%Y-%m-%d"))

        trading = self.config_loader.get_trading_config()
        st_cfg = self.config_loader.get_supertrend_config()
        underlying = str(trading.get("underlying", "NIFTY"))
        timeframe = int(st_cfg.get("timeframe_minutes", 5))

        spot = self.market_data.fetch_spot(underlying)
        self.state.spot_price = spot

        candle = self.market_data.fetch_latest_candle(underlying, timeframe=timeframe)
        if candle:
            self.state.candle.open = candle.open
            self.state.candle.high = candle.high
            self.state.candle.low = candle.low
            self.state.candle.close = candle.close
            self.state.candle.timestamp = candle.timestamp
            if spot is None and candle.close is not None:
                spot = candle.close
                self.state.spot_price = spot

        st_result = None
        if bool(st_cfg.get("enabled", True)):
            series = self.market_data.fetch_candle_series(
                underlying, timeframe=timeframe
            )
            if series and series.closes:
                st_result = self._st_engine.evaluate(
                    series.highs,
                    series.lows,
                    series.closes,
                    last_timestamp=series.last_timestamp,
                )
                self.state.supertrend_value = st_result.value
                self.state.supertrend_direction = st_result.direction.value

        call_ltp = put_ltp = None
        if self.state.call.custom_symbol or self.state.call.trading_symbol:
            call_ltp, put_ltp = self.market_data.fetch_option_ltps(
                self.state.call.custom_symbol or self.state.call.trading_symbol,
                self.state.put.custom_symbol or self.state.put.trading_symbol,
            )
            self._update_leg_mark(self.state.call, call_ltp)
            self._update_leg_mark(self.state.put, put_ltp)
            if self.state.call.status == "TRAILING" and call_ltp is not None:
                self.order_manager.update_trailing("CALL", call_ltp)
            if self.state.put.status == "TRAILING" and put_ltp is not None:
                self.order_manager.update_trailing("PUT", put_ltp)

        decision = self.strategy.evaluate(
            self.state,
            now=now,
            call_ltp=call_ltp,
            put_ltp=put_ltp,
            supertrend=st_result,
        )
        if decision.supertrend_direction:
            self.state.supertrend_direction = decision.supertrend_direction

        try:
            self._execute_decision(decision)
            self.state.clear_error()
        except OrderManagerError as exc:
            logger.error("Order error: %s", exc.message)
            self.state.set_error(exc.message)
        except Exception as exc:
            logger.exception("Poll cycle failed")
            self.state.set_error(str(exc))

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        next_poll = (now + timedelta(seconds=self.state.poll_interval)).isoformat()
        mem_mb, cpu_pct = self._resource_usage()
        self.state.update_poll_meta(
            api_response_ms=round(elapsed_ms, 1),
            next_poll_at=next_poll,
            memory_mb=mem_mb,
            cpu_percent=cpu_pct,
        )
        self._refresh_combined_pnl()

        snapshot = self.state.snapshot()
        logger.info(build_poll_summary_log(snapshot))

        bot_cfg = self.config_loader.get_bot_config()
        always = bool(bot_cfg.get("always_refresh_cli", True))
        every = int(bot_cfg.get("show_last_polls", bot_cfg.get("cli_refresh_every", 3)))
        if always or (every > 0 and self.state.poll_count % every == 0):
            logger.info("CLI DASHBOARD\n%s", build_poll_dashboard(snapshot))

    def _execute_decision(self, decision) -> None:
        action = decision.action

        if action == "WAIT":
            self.state.phase = self.state.PHASE_WAITING
            return

        if action == "ENTER":
            logger.info("Entry signal: %s", decision.reason)
            self.order_manager.enter_straddle()
            self.state.phase = self.state.PHASE_MONITORING_ST
            return

        if action == "CONFIRM_BUY":
            logger.info("Supertrend BUY confirmation — exit PUT, trail CALL")
            self.order_manager.exit_leg("PUT", decision.reason)
            self.order_manager.enable_trailing("CALL")
            self.state.supertrend_confirmed = True
            self.state.remaining_leg = "CALL"
            self.state.exited_leg = "PUT"
            self.state.phase = self.state.PHASE_CALL_ONLY
            self.state.supertrend_direction = "BUY"
            return

        if action == "CONFIRM_SELL":
            logger.info("Supertrend SELL confirmation — exit CALL, trail PUT")
            self.order_manager.exit_leg("CALL", decision.reason)
            self.order_manager.enable_trailing("PUT")
            self.state.supertrend_confirmed = True
            self.state.remaining_leg = "PUT"
            self.state.exited_leg = "CALL"
            self.state.phase = self.state.PHASE_PUT_ONLY
            self.state.supertrend_direction = "SELL"
            return

        if action == "EXIT_CALL":
            self.order_manager.exit_leg("CALL", decision.reason)
            if self.state.put.status not in {"OPEN", "TRAILING"}:
                self.state.phase = self.state.PHASE_FLAT
                self.state.square_off_done = True
                self.state.remaining_leg = None
            elif self.state.put.status in {"OPEN", "TRAILING"}:
                self.state.remaining_leg = "PUT"
                self.state.phase = self.state.PHASE_PUT_ONLY
            return

        if action == "EXIT_PUT":
            self.order_manager.exit_leg("PUT", decision.reason)
            if self.state.call.status not in {"OPEN", "TRAILING"}:
                self.state.phase = self.state.PHASE_FLAT
                self.state.square_off_done = True
                self.state.remaining_leg = None
            elif self.state.call.status in {"OPEN", "TRAILING"}:
                self.state.remaining_leg = "CALL"
                self.state.phase = self.state.PHASE_CALL_ONLY
            return

        if action == "EXIT_ALL":
            self.order_manager.exit_all_open(reason=decision.reason)
            self.state.remaining_leg = None
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

    @staticmethod
    def _resource_usage() -> tuple[float | None, float | None]:
        if psutil is None:
            return None, None
        try:
            process = psutil.Process()
            mem_mb = round(process.memory_info().rss / (1024 * 1024), 1)
            cpu_pct = round(process.cpu_percent(interval=None), 1)
            return mem_mb, cpu_pct
        except Exception:
            return None, None


_trading_bot: TradingBot | None = None


def get_trading_bot() -> TradingBot:
    global _trading_bot
    if _trading_bot is None:
        _trading_bot = TradingBot()
    return _trading_bot
