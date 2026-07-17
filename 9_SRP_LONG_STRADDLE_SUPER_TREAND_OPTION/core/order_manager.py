"""Dual-leg order management for Long Straddle Supertrend Confirmation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from core.config_loader import ConfigLoader, get_config_loader
from core.dhan_client import get_dhan_client
from core.logger import get_logger
from core.market_data import get_market_data_service
from core.option_selector import SelectedStraddle, get_option_selector
from core.position_manager import LegState, OrderRecord, get_bot_state

logger = get_logger()


class OrderManagerError(Exception):
    """Raised when order placement or exit fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# Backwards-compatible alias used by FastAPI handlers
OrderServiceError = OrderManagerError


class OrderManager:
    """Places and exits CALL/PUT orders with trailing support."""

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
        max_retries = int(order_cfg.get("max_retries", 3))

        call_ltp, put_ltp = self.market_data.fetch_option_ltps(
            selected.call.get("security_id"),
            selected.put.get("security_id"),
            call_symbol=selected.call.get("custom_symbol")
            or selected.call.get("trading_symbol"),
            put_symbol=selected.put.get("custom_symbol")
            or selected.put.get("trading_symbol"),
        )
        if call_ltp is None or put_ltp is None:
            raise OrderManagerError("Unable to fetch option LTPs for entry", status_code=502)

        call_price = round(call_ltp + buffer, 2)
        put_price = round(put_ltp + buffer, 2)

        call_result = self._place_leg_with_retry(
            instrument=selected.call,
            transaction_type="BUY",
            quantity=quantity,
            price=call_price,
            dry_run=paper,
            max_retries=max_retries,
            leg_name="CALL",
        )
        put_result = self._place_leg_with_retry(
            instrument=selected.put,
            transaction_type="BUY",
            quantity=quantity,
            price=put_price,
            dry_run=paper,
            max_retries=max_retries,
            leg_name="PUT",
        )

        state = get_bot_state()
        sl_pct = float(risk.get("stop_loss_percent", risk.get("sl_percent", 20)))
        tp_pct = float(risk.get("take_profit_percent", risk.get("tp_percent", 40)))

        self._apply_entry_to_leg(
            state.call,
            selected.call,
            call_result,
            quantity=quantity,
            entry_price=call_price,
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
        state.phase = state.PHASE_MONITORING_ST

        logger.info(
            "Straddle entry complete paper=%s call_order=%s put_order=%s",
            paper,
            call_result.get("order_id"),
            put_result.get("order_id"),
        )
        return selected

    def exit_leg(self, leg: str, reason: str) -> dict[str, Any]:
        """Exit CALL or PUT with a LIMIT sell (LTP - buffer) or MARKET."""
        state = get_bot_state()
        target = state.call if leg.upper() == "CALL" else state.put
        if target.status not in {"OPEN", "TRAILING"}:
            return {"status": "skipped", "reason": f"{leg} not open"}

        order_cfg = self.config_loader.get_order_config()
        buffer = float(order_cfg.get("limit_buffer", 0.5))
        paper = self.config_loader.is_paper_trade()
        max_retries = int(order_cfg.get("max_retries", 3))

        symbol = target.custom_symbol or target.trading_symbol
        ltp = None
        if target.security_id:
            ltp = self.market_data.fetch_ltp_by_security_id(
                target.security_id, "NSE_FNO", label=symbol
            )
        if ltp is None:
            ltp = target.current_price or target.entry_price or 0.0
        sell_price = max(0.05, round(float(ltp) - buffer, 2))

        instrument = {
            "security_id": target.security_id,
            "trading_symbol": target.trading_symbol,
            "custom_symbol": target.custom_symbol,
            "exchange_segment": "NSE_FNO",
            "instrument_name": "OPTIDX",
            "lot_size": None,
        }
        result = self._place_leg_with_retry(
            instrument=instrument,
            transaction_type="SELL",
            quantity=target.quantity,
            price=sell_price,
            dry_run=paper,
            max_retries=max_retries,
            leg_name=leg.upper(),
        )
        target.status = "CLOSED"
        target.current_price = sell_price
        if target.entry_price is not None:
            target.pnl = (sell_price - target.entry_price) * target.quantity
        state.exited_leg = leg.upper()
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
        trail = self.config_loader.get_trail_config()
        target = state.call if leg.upper() == "CALL" else state.put
        if target.status != "OPEN" or target.entry_price is None:
            return
        target.status = "TRAILING"
        peak = target.current_price or target.entry_price
        target.peak_price = peak
        target.trailing_stop = self._compute_trail_stop(peak, trail)
        logger.info(
            "Trailing enabled on %s peak=%.2f trail_stop=%.2f mode=%s",
            leg,
            peak,
            target.trailing_stop,
            trail.get("mode", "percent"),
        )

    def update_trailing(self, leg: str, ltp: float) -> None:
        state = get_bot_state()
        trail = self.config_loader.get_trail_config()
        if not trail.get("enabled", True):
            return
        target = state.call if leg.upper() == "CALL" else state.put
        if target.status != "TRAILING" or target.entry_price is None:
            return
        peak = target.peak_price or target.entry_price
        if ltp > peak:
            peak = ltp
            target.peak_price = peak
            target.trailing_stop = self._compute_trail_stop(peak, trail)

    @staticmethod
    def _compute_trail_stop(peak: float, trail: dict[str, Any]) -> float:
        mode = str(trail.get("mode", "percent")).lower()
        if mode == "points":
            points = float(trail.get("points", 10))
            return round(max(0.05, peak - points), 2)
        percent = float(trail.get("percent", 1.0))
        return round(peak * (1 - percent / 100.0), 2)

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

    def _place_leg_with_retry(
        self,
        *,
        instrument: dict[str, Any],
        transaction_type: str,
        quantity: int,
        price: float,
        dry_run: bool,
        max_retries: int,
        leg_name: str,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts = max(1, max_retries)
        for attempt in range(1, attempts + 1):
            try:
                result = self._place_leg(
                    instrument=instrument,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    price=price,
                    dry_run=dry_run,
                )
                get_bot_state().add_order(
                    OrderRecord(
                        order_id=str(result.get("order_id", "")),
                        leg=leg_name,
                        side=transaction_type,
                        quantity=quantity,
                        price=price,
                        status=str(result.get("status", "")),
                        symbol=instrument.get("trading_symbol"),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )
                )
                return result
            except OrderManagerError as exc:
                last_error = exc
                logger.warning(
                    "Order attempt %s/%s failed for %s: %s",
                    attempt,
                    attempts,
                    leg_name,
                    exc.message,
                )
                if attempt >= attempts:
                    break
        assert last_error is not None
        raise last_error

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
        order_cfg = self.config_loader.get_order_config()
        product_type = str(trading.get("product_type", "INTRADAY")).upper()
        validity = str(trading.get("validity", "DAY")).upper()
        order_type = str(order_cfg.get("order_type", "LIMIT")).upper()

        logger.info(
            "Order %s %s qty=%s price=%s type=%s dry_run=%s sid=%s",
            transaction_type,
            instrument.get("trading_symbol"),
            quantity,
            price,
            order_type,
            dry_run,
            instrument.get("security_id"),
        )

        # Paper mode: never import Dhan_SRP / dhanhq (keeps 1GB AWS RSS low).
        if dry_run:
            return {
                "status": "paper_trade",
                "order_id": f"PAPER-{instrument.get('security_id')}-{transaction_type}",
                "limit_price": price,
                "preview": {
                    "security_id": instrument.get("security_id"),
                    "transaction_type": transaction_type,
                    "quantity": quantity,
                    "price": price,
                    "order_type": order_type,
                    "product_type": product_type,
                },
            }

        dhan = get_dhan_client(self.config_loader)
        try:
            result = dhan.place_order(
                symbol=instrument.get("trading_symbol"),
                security_id=instrument.get("security_id"),
                exchange_segment=instrument.get("exchange_segment", "NSE_FNO"),
                transaction_type=transaction_type,
                quantity=quantity,
                order_type=order_type,
                product_type=product_type,
                price=0 if order_type == "MARKET" else price,
                validity=validity,
                instrument_name=instrument.get("instrument_name", "OPTIDX"),
                lot_size=instrument.get("lot_size"),
                dry_run=False,
            )
        except requests.exceptions.Timeout as exc:
            raise OrderManagerError("Dhan API request timed out", status_code=504) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OrderManagerError(
                "Network error connecting to Dhan API", status_code=503
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected error placing order")
            raise OrderManagerError(str(exc), status_code=500) from exc

        validation = result.get("validation", {})
        if not validation.get("valid", True):
            errors = validation.get("errors", ["Order validation failed"])
            raise OrderManagerError("; ".join(errors), status_code=400)

        response = result.get("response", {})
        if response.get("status") != "success":
            remarks = response.get("remarks") or response
            raise OrderManagerError(f"Dhan order failed: {remarks}", status_code=502)

        data = response.get("data") or {}
        order_id = data.get("orderId") or data.get("order_id")
        if not order_id:
            raise OrderManagerError("Dhan response missing order_id", status_code=502)

        return {
            "status": "success",
            "order_id": str(order_id),
            "limit_price": price,
        }


_order_manager: OrderManager | None = None


def get_order_manager() -> OrderManager:
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager()
    return _order_manager


# Alias matching sibling naming
def get_order_service() -> OrderManager:
    return get_order_manager()
