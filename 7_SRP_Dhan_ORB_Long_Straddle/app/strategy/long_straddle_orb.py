"""Long Straddle + Opening Range Breakout strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.config_loader import ConfigLoader, get_config_loader
from app.state import BotState
from app.utils import _to_ist, is_at_or_after, parse_hhmm


@dataclass
class StrategyDecision:
    """Action recommended by the strategy for the current poll."""

    action: str  # WAIT | ENTER | UPDATE_ORB | BREAKOUT_UP | BREAKOUT_DOWN | EXIT_CALL | EXIT_PUT | EXIT_ALL | NONE
    reason: str = ""
    breakout_status: str = "Inside Range"


class LongStraddleORBStrategy:
    """Pure decision logic for Long Straddle ORB (no broker I/O)."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def evaluate(
        self,
        state: BotState,
        *,
        now: datetime,
        spot: float | None,
        call_ltp: float | None,
        put_ltp: float | None,
    ) -> StrategyDecision:
        strategy = self.config_loader.get_strategy_config()
        risk = self.config_loader.get_risk_config()
        entry_time = str(strategy.get("entry_time", "09:15"))
        square_off = str(strategy.get("square_off_time", "15:15"))
        orb_minutes = int(strategy.get("opening_range_minutes", 15))

        if state.manual_stop_requested:
            return StrategyDecision(action="EXIT_ALL", reason="manual_stop")

        if state.square_off_done or state.phase == BotState.PHASE_FLAT:
            return StrategyDecision(action="NONE", reason="session_flat")

        if is_at_or_after(now, square_off) and state.entry_done:
            return StrategyDecision(action="EXIT_ALL", reason="square_off_time")

        if not state.entry_done:
            if is_at_or_after(now, entry_time):
                return StrategyDecision(action="ENTER", reason="entry_time_reached")
            return StrategyDecision(action="WAIT", reason="before_entry_time")

        # Building ORB during opening range window after entry
        orb_end = self._orb_end_time(entry_time, orb_minutes)
        if not state.orb_complete:
            if _to_ist(now).time() < orb_end:
                return StrategyDecision(action="UPDATE_ORB", reason="building_opening_range")
            return StrategyDecision(action="UPDATE_ORB", reason="finalize_opening_range")

        # Breakout monitoring
        if not state.breakout_done and spot is not None and state.orb_high and state.orb_low:
            if spot > state.orb_high:
                return StrategyDecision(
                    action="BREAKOUT_UP",
                    reason="spot_above_orb_high",
                    breakout_status="Above High",
                )
            if spot < state.orb_low:
                return StrategyDecision(
                    action="BREAKOUT_DOWN",
                    reason="spot_below_orb_low",
                    breakout_status="Below Low",
                )
            return StrategyDecision(
                action="NONE",
                reason="inside_range",
                breakout_status="Inside Range",
            )

        # Risk exits on remaining trailing/open leg(s)
        call_exit = self._leg_exit_signal(state.call, call_ltp, risk)
        if call_exit:
            return StrategyDecision(action="EXIT_CALL", reason=call_exit)

        put_exit = self._leg_exit_signal(state.put, put_ltp, risk)
        if put_exit:
            return StrategyDecision(action="EXIT_PUT", reason=put_exit)

        status = "Inside Range"
        if spot is not None and state.orb_high and state.orb_low:
            if spot > state.orb_high:
                status = "Above High"
            elif spot < state.orb_low:
                status = "Below Low"
        return StrategyDecision(action="NONE", reason="hold", breakout_status=status)

    @staticmethod
    def _orb_end_time(entry_time: str, opening_range_minutes: int):
        base = parse_hhmm(entry_time)
        dt = datetime(2000, 1, 1, base.hour, base.minute, base.second) + timedelta(
            minutes=opening_range_minutes
        )
        return dt.time()

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


def get_strategy(config_loader: ConfigLoader | None = None) -> LongStraddleORBStrategy:
    return LongStraddleORBStrategy(config_loader)
