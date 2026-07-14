"""Long Straddle + EMA 9/21 Confirmation strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config_loader import ConfigLoader, get_config_loader
from app.ema import EmaResult
from app.state import BotState
from app.utils import is_at_or_after


@dataclass
class StrategyDecision:
    """Action recommended by the strategy for the current poll."""

    action: str  # WAIT | ENTER | CONFIRM_BULLISH | CONFIRM_BEARISH | EXIT_CALL | EXIT_PUT | EXIT_ALL | NONE
    reason: str = ""
    ema_trend: str = "NEUTRAL"


class LongStraddleEMAStrategy:
    """Pure decision logic for Long Straddle EMA Confirmation (no broker I/O)."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def evaluate(
        self,
        state: BotState,
        *,
        now: datetime,
        call_ltp: float | None,
        put_ltp: float | None,
        ema: EmaResult | None = None,
    ) -> StrategyDecision:
        strategy = self.config_loader.get_strategy_config()
        risk = self.config_loader.get_risk_config()
        ema_cfg = self.config_loader.get_ema_config()
        entry_time = str(strategy.get("entry_time", "09:20"))
        square_off = str(strategy.get("square_off_time", "15:20"))
        ema_enabled = bool(ema_cfg.get("enabled", True))

        trend = ema.trend.value if ema else state.ema_trend or "NEUTRAL"

        if state.manual_stop_requested:
            return StrategyDecision(action="EXIT_ALL", reason="manual_stop", ema_trend=trend)

        if state.square_off_done or state.phase == BotState.PHASE_FLAT:
            return StrategyDecision(action="NONE", reason="session_flat", ema_trend=trend)

        if is_at_or_after(now, square_off) and state.entry_done:
            return StrategyDecision(action="EXIT_ALL", reason="square_off_time", ema_trend=trend)

        if not state.entry_done:
            if is_at_or_after(now, entry_time):
                return StrategyDecision(action="ENTER", reason="entry_time_reached", ema_trend=trend)
            return StrategyDecision(action="WAIT", reason="before_entry_time", ema_trend=trend)

        # After entry: wait for EMA confirmation (once per session)
        if ema_enabled and not state.ema_confirmed and ema is not None and ema.cross_detected:
            if ema.cross_direction == "BULLISH":
                return StrategyDecision(
                    action="CONFIRM_BULLISH",
                    reason="ema9_crossed_above_ema21",
                    ema_trend="BULLISH",
                )
            if ema.cross_direction == "BEARISH":
                return StrategyDecision(
                    action="CONFIRM_BEARISH",
                    reason="ema9_crossed_below_ema21",
                    ema_trend="BEARISH",
                )

        # Risk exits on open/trailing legs
        call_exit = self._leg_exit_signal(state.call, call_ltp, risk)
        if call_exit:
            return StrategyDecision(action="EXIT_CALL", reason=call_exit, ema_trend=trend)

        put_exit = self._leg_exit_signal(state.put, put_ltp, risk)
        if put_exit:
            return StrategyDecision(action="EXIT_PUT", reason=put_exit, ema_trend=trend)

        return StrategyDecision(action="NONE", reason="hold", ema_trend=trend)

    @staticmethod
    def _leg_exit_signal(leg: Any, ltp: float | None, risk: dict[str, Any]) -> str | None:
        if leg.status not in {"OPEN", "TRAILING"} or ltp is None or leg.entry_price is None:
            return None
        if leg.target is not None and ltp >= leg.target:
            return "take_profit"
        if leg.stop_loss is not None and ltp <= leg.stop_loss:
            return "stop_loss"
        if (
            risk.get("trailing_enabled", True)
            and leg.status == "TRAILING"
            and leg.trailing_stop is not None
            and ltp <= leg.trailing_stop
        ):
            return "trailing_stop"
        return None


def get_strategy(config_loader: ConfigLoader | None = None) -> LongStraddleEMAStrategy:
    return LongStraddleEMAStrategy(config_loader)
