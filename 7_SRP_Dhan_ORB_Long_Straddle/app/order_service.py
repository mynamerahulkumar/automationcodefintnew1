"""Dual-leg order management for Long Straddle ORB."""

from __future__ import annotations

from typing import Any

import requests

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhan_client
from app.logger import get_logger
from app.market_data import get_market_data_service
from app.option_selector import SelectedStraddle, get_option_selector
from app.state import LegState, get_bot_state

logger = get_logger()


class OrderServiceError(Exception):
    """Raised when order placement or exit fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class OrderService:
    """Places and exits CALL/PUT LIMIT orders."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()
        self.market_data = get_market_data_service()
        self.option_selector = get_option_selector()

    def enter_straddle(self) -> SelectedStraddle:
        """Select strikes and BUY both ATM (or configured) CALL and PUT."""
        selected = self.option_selector.select()
        trading = self.config_loader.get_trading_config()
        order_cfg = self.config_loader.get_order_config()
        risk = self.config_loader.get_risk_config()
        quantity = int(trading["quantity"])
        buffer = float(order_cfg.get("limit_buffer", 0.5))
        paper = self.config_loader.is_paper_trade()

        call_ltp = self.market_data.fetch_ltp_for_symbol(
            selected.call.get("custom_symbol") or selected.call["trading_symbol"]
        )
        put_ltp = self.market_data.fetch_ltp_for_symbol(
            selected.put.get("custom_symbol") or selected.put["trading_symbol"]
        )
        if call_ltp is None or put_ltp is None:
            raise OrderServiceError("Unable to fetch option LTPs for entry", status_code=502)

        call_price = round(call_ltp + buffer, 2)
        put_price = round(put_ltp + buffer, 2)

        call_result = self._place_leg(
            instrument=selected.call,
            transaction_type="BUY",
            quantity=quantity,
            price=call_price,
            dry_run=paper,
        )
        put_result = self._place_leg(
            instrument=selected.put,
            transaction_type="BUY",
            quantity=quantity,
            price=put_price,
            dry_run=paper,
        )

        state = get_bot_state()
        sl_pct = float(risk.get("stop_loss_percent", 25))
        tp_pct = float(risk.get("take_profit_percent", 50))

        self._apply_entry_to_leg(
            state.call,
            selected.call,
            call_result,
            quantity=quantity,
            entry_price=call_price if paper or call_result.get("status") == "paper_trade" else call_price,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            strike=selected.call_strike,
        )
        self._apply_entry_to_leg(
            state.put,
            selected.put,
            put_result,
            quantity=quantity,
            entry_price=put_price,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            strike=selected.put_strike,
        )

        state.underlying = selected.underlying
        state.expiry = selected.expiry
        state.atm_strike = selected.atm_strike
        state.spot_price = selected.spot
        state.entry_done = True
        state.phase = state.PHASE_BUILDING_ORB

        logger.info(
            "Straddle entry complete paper=%s call_order=%s put_order=%s",
            paper,
            call_result.get("order_id"),
            put_result.get("order_id"),
        )
        return selected

    def exit_leg(self, leg: str, reason: str) -> dict[str, Any]:
        """Exit CALL or PUT with a LIMIT sell (LTP - buffer)."""
        state = get_bot_state()
        target = state.call if leg.upper() == "CALL" else state.put
        if target.status not in {"OPEN", "TRAILING"}:
            return {"status": "skipped", "reason": f"{leg} not open"}

        order_cfg = self.config_loader.get_order_config()
        buffer = float(order_cfg.get("limit_buffer", 0.5))
        paper = self.config_loader.is_paper_trade()

        symbol = target.custom_symbol or target.trading_symbol
        ltp = self.market_data.fetch_ltp_for_symbol(symbol or "")
        if ltp is None:
            ltp = target.current_price or target.entry_price or 0.0
        sell_price = max(0.05, round(float(ltp) - buffer, 2))

        instrument = {
            "security_id": target.security_id,
            "trading_symbol": target.trading_symbol,
            "exchange_segment": "NSE_FNO",
            "instrument_name": "OPTIDX",
            "lot_size": None,
        }
        result = self._place_leg(
            instrument=instrument,
            transaction_type="SELL",
            quantity=target.quantity,
            price=sell_price,
            dry_run=paper,
        )
        target.status = "CLOSED"
        target.current_price = sell_price
        if target.entry_price is not None:
            target.pnl = (sell_price - target.entry_price) * target.quantity
        logger.info("Exited %s reason=%s order=%s", leg, reason, result.get("order_id"))
        return result

    def exit_all_open(self, reason: str = "manual_stop") -> list[dict[str, Any]]:
        results = []
        state = get_bot_state()
        for leg_name, leg in (("CALL", state.call), ("PUT", state.put)):
            if leg.status in {"OPEN", "TRAILING"}:
                results.append(self.exit_leg(leg_name, reason))
        state.phase = state.PHASE_FLAT
        state.square_off_done = True
        return results

    def enable_trailing(self, leg: str) -> None:
        state = get_bot_state()
        risk = self.config_loader.get_risk_config()
        target = state.call if leg.upper() == "CALL" else state.put
        if target.status != "OPEN" or target.entry_price is None:
            return
        target.status = "TRAILING"
        peak = target.current_price or target.entry_price
        target.peak_price = peak
        trail_pct = float(risk.get("trailing_percent", 10))
        target.trailing_stop = round(peak * (1 - trail_pct / 100.0), 2)
        logger.info(
            "Trailing enabled on %s peak=%.2f trail_stop=%.2f",
            leg,
            peak,
            target.trailing_stop,
        )

    def update_trailing(self, leg: str, ltp: float) -> None:
        state = get_bot_state()
        risk = self.config_loader.get_risk_config()
        if not risk.get("trailing_enabled", True):
            return
        target = state.call if leg.upper() == "CALL" else state.put
        if target.status != "TRAILING" or target.entry_price is None:
            return
        peak = target.peak_price or target.entry_price
        if ltp > peak:
            peak = ltp
            target.peak_price = peak
            trail_pct = float(risk.get("trailing_percent", 10))
            target.trailing_stop = round(peak * (1 - trail_pct / 100.0), 2)

    def _apply_entry_to_leg(
        self,
        leg: LegState,
        instrument: dict[str, Any],
        result: dict[str, Any],
        *,
        quantity: int,
        entry_price: float,
        sl_pct: float,
        tp_pct: float,
        strike: float,
    ) -> None:
        leg.status = "OPEN"
        leg.order_id = result.get("order_id")
        leg.security_id = str(instrument["security_id"])
        leg.trading_symbol = instrument.get("trading_symbol")
        leg.custom_symbol = instrument.get("custom_symbol")
        leg.strike = strike
        leg.quantity = quantity
        leg.entry_price = entry_price
        leg.current_price = entry_price
        leg.pnl = 0.0
        leg.stop_loss = round(entry_price * (1 - sl_pct / 100.0), 2)
        leg.target = round(entry_price * (1 + tp_pct / 100.0), 2)
        leg.trailing_stop = None
        leg.peak_price = entry_price

    def _place_leg(
        self,
        *,
        instrument: dict[str, Any],
        transaction_type: str,
        quantity: int,
        price: float,
        dry_run: bool,
    ) -> dict[str, Any]:
        trading = self.config_loader.get_trading_config()
        product_type = str(trading.get("product_type", "INTRADAY")).upper()
        validity = str(trading.get("validity", "DAY")).upper()
        dhan = get_dhan_client(self.config_loader)

        logger.info(
            "Order %s %s qty=%s price=%s dry_run=%s sid=%s",
            transaction_type,
            instrument.get("trading_symbol"),
            quantity,
            price,
            dry_run,
            instrument.get("security_id"),
        )

        try:
            result = dhan.place_order(
                symbol=instrument.get("trading_symbol"),
                security_id=instrument.get("security_id"),
                exchange_segment=instrument.get("exchange_segment", "NSE_FNO"),
                transaction_type=transaction_type,
                quantity=quantity,
                order_type="LIMIT",
                product_type=product_type,
                price=price,
                validity=validity,
                instrument_name=instrument.get("instrument_name", "OPTIDX"),
                lot_size=instrument.get("lot_size"),
                dry_run=dry_run,
            )
        except requests.exceptions.Timeout as exc:
            raise OrderServiceError("Dhan API request timed out", status_code=504) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OrderServiceError("Network error connecting to Dhan API", status_code=503) from exc
        except Exception as exc:
            logger.exception("Unexpected error placing order")
            raise OrderServiceError(str(exc), status_code=500) from exc

        validation = result.get("validation", {})
        if not validation.get("valid", True):
            errors = validation.get("errors", ["Order validation failed"])
            raise OrderServiceError("; ".join(errors), status_code=400)

        if dry_run:
            return {
                "status": "paper_trade",
                "order_id": f"PAPER-{instrument.get('security_id')}-{transaction_type}",
                "limit_price": price,
                "preview": result.get("preview"),
            }

        response = result.get("response", {})
        if response.get("status") != "success":
            remarks = response.get("remarks") or response
            raise OrderServiceError(f"Dhan order failed: {remarks}", status_code=502)

        data = response.get("data") or {}
        order_id = data.get("orderId") or data.get("order_id")
        if not order_id:
            raise OrderServiceError("Dhan response missing order_id", status_code=502)

        return {
            "status": "success",
            "order_id": str(order_id),
            "limit_price": price,
        }


_order_service: OrderService | None = None


def get_order_service() -> OrderService:
    global _order_service
    if _order_service is None:
        _order_service = OrderService()
    return _order_service
