"""ATM / ITM / OTM option strike selection for the straddle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.config_loader import ConfigLoader, get_config_loader
from core.instrument_lookup import (
    get_underlying_security_id,
    resolve_expiry,
    resolve_option_security,
)
from core.logger import get_logger
from core.market_data import get_market_data_service
from core.utils import INDEX_STEP

logger = get_logger()


@dataclass
class SelectedStraddle:
    """Resolved call/put pair for entry."""

    underlying: str
    expiry: str
    spot: float
    atm_strike: float
    call_strike: float
    put_strike: float
    call: dict[str, Any]
    put: dict[str, Any]
    selection_type: str
    strike_offset: int


class OptionSelector:
    """Selects CE/PE via REST spot + arithmetic ATM + CSV security IDs."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.market_data = get_market_data_service()

    def select(self) -> SelectedStraddle:
        trading = self.config_loader.get_trading_config()
        option_sel = self.config_loader.get_option_selection()
        security_cfg = self.config_loader.get_security_config()

        underlying = str(trading.get("underlying", "NIFTY")).upper()
        exchange = str(trading.get("exchange", "NSE")).upper()
        expiry_cfg = str(trading.get("expiry", "nearest"))
        sel_type = str(option_sel.get("type", "ATM")).upper()
        offset = int(option_sel.get("offset", option_sel.get("strike_offset", 0)))

        expiry = resolve_expiry(expiry_cfg, underlying, exchange)
        _ = get_underlying_security_id(
            underlying, security_cfg.get("security_id") or None
        )

        spot = self.market_data.fetch_spot(underlying)
        if spot is None or spot <= 0:
            raise ValueError(f"Unable to fetch spot LTP for {underlying}")

        step = INDEX_STEP.get(underlying, 50)
        atm_strike = float(round(spot / step) * step)
        call_strike, put_strike = self._strikes_for_selection(
            sel_type=sel_type,
            offset=offset,
            atm_strike=atm_strike,
            step=step,
        )

        call = resolve_option_security(
            underlying=underlying,
            expiry=expiry,
            strike=call_strike,
            option_type="CE",
            exchange=exchange,
        )
        put = resolve_option_security(
            underlying=underlying,
            expiry=expiry,
            strike=put_strike,
            option_type="PE",
            exchange=exchange,
        )

        logger.info(
            "Selected straddle %s expiry=%s spot=%.2f atm=%.0f CE=%.0f PE=%.0f type=%s offset=%s",
            underlying,
            expiry,
            spot,
            atm_strike,
            call_strike,
            put_strike,
            sel_type,
            offset,
        )

        return SelectedStraddle(
            underlying=underlying,
            expiry=expiry,
            spot=float(spot),
            atm_strike=float(atm_strike),
            call_strike=float(call_strike),
            put_strike=float(put_strike),
            call=call,
            put=put,
            selection_type=sel_type,
            strike_offset=offset,
        )

    @staticmethod
    def _strikes_for_selection(
        *,
        sel_type: str,
        offset: int,
        atm_strike: float,
        step: int,
    ) -> tuple[float, float]:
        """Return (call_strike, put_strike) using arithmetic only (no Dhan_SRP)."""
        if sel_type == "ATM" or offset == 0:
            return atm_strike, atm_strike
        if sel_type == "OTM":
            return atm_strike + offset * step, atm_strike - offset * step
        return atm_strike - offset * step, atm_strike + offset * step


_option_selector: OptionSelector | None = None


def get_option_selector() -> OptionSelector:
    global _option_selector
    if _option_selector is None:
        _option_selector = OptionSelector()
    return _option_selector
