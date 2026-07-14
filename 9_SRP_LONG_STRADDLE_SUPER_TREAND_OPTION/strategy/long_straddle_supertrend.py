"""Long Straddle + Supertrend Confirmation strategy evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.config_loader import ConfigLoader, get_config_loader
from core.position_manager import BotState
from core.utils import is_at_or_after
from indicator.supertrend import SupertrendResult


@dataclass
class StrategyDecision:
    """Action recommended by the strategy for the current poll."""

    action: str  # WAIT | ENTER | CONFIRM_BUY | CONFIRM_SELL | EXIT_CALL | EXIT_PUT | EXIT_ALL | NONE
    reason: str = ""
    supertrend_direction: str = "NEUTRAL"


class LongStraddleSupertrendStrategy:
    """Pure decision logic for Long Straddle Supertrend Confirmation (no broker I/O)."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def evaluate(
        self,
        state: BotState,
        *,
        now: datetime,
        call_ltp: float | None,
        put_ltp: float | None,
        supertrend: SupertrendResult | None = None,
    ) -> StrategyDecision:
        strategy = self.config_loader.get_strategy_config()
        risk = self.config_loader.get_risk_config()
        trail = self.config_loader.get_trail_config()
        st_cfg = self.config_loader.get_supertrend_config()
        entry_time = str(strategy.get("entry_time", "09:15"))
        square_off = str(strategy.get("square_off_time", "15:20"))
        st_enabled = bool(st_cfg.get("enabled", True))

        direction = (
            supertrend.direction.value
            if supertrend
            else state.supertrend_direction or "NEUTRAL"
        )

        if state.manual_stop_requested:
            return StrategyDecision(
                action="EXIT_ALL", reason="manual_stop", supertrend_direction=direction
            )

        if state.square_off_done or state.phase == BotState.PHASE_FLAT:
            return StrategyDecision(
                action="NONE", reason="session_flat", supertrend_direction=direction
            )

        if is_at_or_after(now, square_off) and state.entry_done:
            return StrategyDecision(
                action="EXIT_ALL",
                reason="square_off_time",
                supertrend_direction=direction,
            )

        if not state.entry_done:
            if is_at_or_after(now, entry_time):
                return StrategyDecision(
                    action="ENTER",
                    reason="entry_time_reached",
                    supertrend_direction=direction,
                )
            return StrategyDecision(
                action="WAIT",
                reason="before_entry_time",
                supertrend_direction=direction,
            )

        # After entry: confirm once on first valid Supertrend BUY/SELL regime
        if (
            st_enabled
            and not state.supertrend_confirmed
            and supertrend is not None
            and direction in {"BUY", "SELL"}
        ):
            if direction == "BUY":
                return StrategyDecision(
                    action="CONFIRM_BUY",
                    reason="supertrend_buy",
                    supertrend_direction="BUY",
                )
            return StrategyDecision(
                action="CONFIRM_SELL",
                reason="supertrend_sell",
                supertrend_direction="SELL",
            )

        # Risk exits on open/trailing legs
        call_exit = self._leg_exit_signal(state.call, call_ltp, risk, trail)
        if call_exit:
            return StrategyDecision(
                action="EXIT_CALL", reason=call_exit, supertrend_direction=direction
            )

        put_exit = self._leg_exit_signal(state.put, put_ltp, risk, trail)
        if put_exit:
            return StrategyDecision(
                action="EXIT_PUT", reason=put_exit, supertrend_direction=direction
            )

        return StrategyDecision(
            action="NONE", reason="hold", supertrend_direction=direction
        )

    @staticmethod
    def _leg_exit_signal(
        leg: Any,
        ltp: float | None,
        risk: dict[str, Any],
        trail: dict[str, Any],
    ) -> str | None:
        if leg.status not in {"OPEN", "TRAILING"} or ltp is None or leg.entry_price is None:
            return None
        if leg.target is not None and ltp >= leg.target:
            return "take_profit"
        if leg.stop_loss is not None and ltp <= leg.stop_loss:
            return "stop_loss"
        if (
            trail.get("enabled", True)
            and leg.status == "TRAILING"
            and leg.trailing_stop is not None
            and ltp <= leg.trailing_stop
        ):
            return "trailing_stop"
        return None


def get_strategy(
    config_loader: ConfigLoader | None = None,
) -> LongStraddleSupertrendStrategy:
    return LongStraddleSupertrendStrategy(config_loader)
