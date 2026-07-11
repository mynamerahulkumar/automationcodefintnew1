"""Order placement service using Dhan_SRP."""

from __future__ import annotations

from typing import Any

import requests

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhan_client
from app.logger import get_logger
from app.security_master import resolve_instrument
from app.state import get_bot_state

logger = get_logger()


class OrderServiceError(Exception):
    """Raised when order placement fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class OrderService:
    """Places LIMIT orders for stocks and options based on configuration."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def reload_config(self) -> dict[str, Any]:
        """Reload configuration and return a summary."""
        self.config_loader.reload()
        return self.config_loader.summary()

    def place_order_from_config(self) -> dict[str, Any]:
        """Read config, resolve security, and place a LIMIT order."""
        trading = self.config_loader.get_trading_config()
        transaction_type = str(trading.get("transaction_type", "BUY")).upper()
        limit_price = float(trading.get("limit_price", 0) or 0)
        if limit_price <= 0:
            limit_price = self._fetch_ltp(trading)
        return self._place_order(
            transaction_type=transaction_type,
            limit_price=limit_price,
            dry_run_override=None,
        )

    def place_signal_order(self, signal: str, limit_price: float | None = None) -> dict[str, Any]:
        """Place a LIMIT order triggered by a strategy signal."""
        trading = self.config_loader.get_trading_config()
        bot = self.config_loader.get_bot_config()
        state = get_bot_state()

        if bot.get("one_position_only") and state.should_skip_position(
            signal, one_position_only=True
        ):
            logger.info("Skipping %s — one_position_only guard", signal)
            return {"status": "skipped", "reason": "one_position_only", "signal": signal}

        price = limit_price
        if price is None or price <= 0:
            config_price = float(trading.get("limit_price", 0) or 0)
            price = config_price if config_price > 0 else self._fetch_ltp(trading)

        paper_trade = bool(bot.get("paper_trade", False))
        return self._place_order(
            transaction_type=signal,
            limit_price=price,
            dry_run_override=paper_trade,
        )

    def _fetch_ltp(self, trading: dict[str, Any]) -> float:
        """Fetch last traded price for limit order pricing."""
        stock_name = str(trading.get("stock_name", ""))
        try:
            dhan = get_dhan_client(self.config_loader)
            ltp_data = dhan.get_ltp_data(stock_name)
            if isinstance(ltp_data, dict):
                for value in ltp_data.values():
                    if isinstance(value, (int, float)) and value > 0:
                        return float(value)
            raise OrderServiceError(f"Could not fetch LTP for {stock_name}", status_code=502)
        except OrderServiceError:
            raise
        except Exception as exc:
            raise OrderServiceError(f"LTP fetch failed: {exc}", status_code=502) from exc

    def _place_order(
        self,
        *,
        transaction_type: str,
        limit_price: float,
        dry_run_override: bool | None,
    ) -> dict[str, Any]:
        trading = self.config_loader.get_trading_config()
        risk = self.config_loader.get_risk_config()
        bot = self.config_loader.get_bot_config()
        dry_run = bool(bot.get("paper_trade", False)) if dry_run_override is None else dry_run_override

        quantity = int(trading["quantity"])
        product_type = str(trading.get("product_type", "INTRADAY")).upper()
        validity = str(trading.get("validity", "DAY")).upper()
        stock_name = str(trading.get("stock_name", ""))

        logger.info(
            "Placing order: segment=%s symbol=%s side=%s qty=%s price=%s dry_run=%s",
            trading.get("segment"),
            stock_name,
            transaction_type,
            quantity,
            limit_price,
            dry_run,
        )

        try:
            instrument = resolve_instrument(trading)
        except (ValueError, FileNotFoundError) as exc:
            raise OrderServiceError(str(exc), status_code=404) from exc

        dhan = get_dhan_client(self.config_loader)

        try:
            result = dhan.place_order(
                symbol=instrument["trading_symbol"],
                security_id=instrument["security_id"],
                exchange_segment=instrument["exchange_segment"],
                transaction_type=transaction_type,
                quantity=quantity,
                order_type="LIMIT",
                product_type=product_type,
                price=limit_price,
                validity=validity,
                instrument_name=instrument["instrument_name"],
                lot_size=instrument.get("lot_size"),
                dry_run=dry_run,
            )
        except requests.exceptions.Timeout as exc:
            raise OrderServiceError("Dhan API request timed out", status_code=504) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OrderServiceError("Network error connecting to Dhan API", status_code=503) from exc
        except ValueError as exc:
            raise OrderServiceError(str(exc), status_code=400) from exc
        except Exception as exc:
            message = str(exc)
            if "credential" in message.lower() or "auth" in message.lower():
                raise OrderServiceError(
                    "Dhan authentication failed. Check client_id and access_token.",
                    status_code=401,
                ) from exc
            logger.exception("Unexpected error placing order")
            raise OrderServiceError(message, status_code=500) from exc

        validation = result.get("validation", {})
        if not validation.get("valid", True):
            errors = validation.get("errors", ["Order validation failed"])
            raise OrderServiceError("; ".join(errors), status_code=400)

        risk_payload = {
            "target_percent": risk.get("target_percent"),
            "stoploss_percent": risk.get("stoploss_percent"),
            "trailing_sl": risk.get("trailing_sl", False),
        }

        if dry_run:
            return {
                "status": "paper_trade",
                "security_id": instrument["security_id"],
                "symbol": instrument.get("trading_symbol", stock_name),
                "transaction_type": transaction_type,
                "limit_price": limit_price,
                "preview": result.get("preview"),
                "validation": validation,
                "risk": risk_payload,
            }

        response = result.get("response", {})
        if response.get("status") != "success":
            remarks = response.get("remarks") or response
            raise OrderServiceError(f"Dhan order failed: {remarks}", status_code=502)

        data = response.get("data") or {}
        order_id = data.get("orderId") or data.get("order_id")
        if not order_id:
            raise OrderServiceError("Dhan response missing order_id", status_code=502)

        logger.info("Order placed successfully: order_id=%s", order_id)
        return {
            "status": "success",
            "order_id": str(order_id),
            "security_id": instrument["security_id"],
            "symbol": instrument.get("trading_symbol", stock_name),
            "transaction_type": transaction_type,
            "limit_price": limit_price,
            "risk": risk_payload,
        }


_order_service: OrderService | None = None


def get_order_service() -> OrderService:
    """Return the shared order service instance."""
    global _order_service
    if _order_service is None:
        _order_service = OrderService()
    return _order_service
