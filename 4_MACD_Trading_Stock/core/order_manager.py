"""LIMIT order placement via Dhan_SRP with retry and buffer pricing."""

from __future__ import annotations

import time
from typing import Any

import requests

from core.config_loader import ConfigLoader, get_config_loader, resolve_instrument
from core.dhan_client import get_dhan_client
from core.logger import get_logger

logger = get_logger()

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class OrderManagerError(Exception):
    """Raised when order placement fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class OrderManager:
    """Places LIMIT orders for stocks and options."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or get_config_loader()

    def calculate_limit_price(self, signal: str, current_price: float) -> float:
        """
        Apply configurable buffer to current price.

        BUY: price + buffer (e.g. 100 -> 100.10)
        SELL: price - buffer (e.g. 100 -> 99.90)
        """
        trading = self.config_loader.get_trading_config()
        buffer = float(trading.get("limit_buffer", 0.10))
        side = signal.upper()
        if side == "BUY":
            return round(current_price + buffer, 2)
        if side == "SELL":
            return round(current_price - buffer, 2)
        raise OrderManagerError(f"Invalid signal for limit price: {signal}")

    def place_signal_order(self, signal: str, current_price: float) -> dict[str, Any]:
        """Place a LIMIT order for a strategy signal with retries."""
        limit_price = self.calculate_limit_price(signal, current_price)
        trading = self.config_loader.get_trading_config()
        dry_run = bool(trading.get("paper_trade", False))

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return self._place_order(
                    transaction_type=signal.upper(),
                    limit_price=limit_price,
                    dry_run=dry_run,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                logger.warning(
                    "Order attempt %s/%s failed (network): %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
            except OrderManagerError:
                raise
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Order attempt %s/%s failed: %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

        raise OrderManagerError(
            f"Order failed after {MAX_RETRIES} attempts: {last_error}",
            status_code=503,
        )

    def _place_order(
        self,
        *,
        transaction_type: str,
        limit_price: float,
        dry_run: bool,
    ) -> dict[str, Any]:
        trading = self.config_loader.get_trading_config()
        risk = self.config_loader.get_risk_config()

        quantity = int(trading["quantity"])
        product_type = str(trading.get("product_type", "CNC")).upper()
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
            instrument = resolve_instrument(self.config_loader.get_market_config())
        except (ValueError, FileNotFoundError) as exc:
            raise OrderManagerError(str(exc), status_code=404) from exc

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
            raise OrderManagerError("Dhan API request timed out", status_code=504) from exc
        except requests.exceptions.ConnectionError as exc:
            raise OrderManagerError("Network error connecting to Dhan API", status_code=503) from exc
        except ValueError as exc:
            raise OrderManagerError(str(exc), status_code=400) from exc
        except Exception as exc:
            message = str(exc)
            if "credential" in message.lower() or "auth" in message.lower():
                raise OrderManagerError(
                    "Dhan authentication failed. Check client_id and access_token.",
                    status_code=401,
                ) from exc
            logger.exception("Unexpected error placing order")
            raise OrderManagerError(message, status_code=500) from exc

        validation = result.get("validation", {})
        if not validation.get("valid", True):
            errors = validation.get("errors", ["Order validation failed"])
            raise OrderManagerError("; ".join(errors), status_code=400)

        risk_payload = {
            "take_profit_percent": risk.get("take_profit_percent"),
            "stop_loss_percent": risk.get("stop_loss_percent"),
        }

        if dry_run:
            logger.info("Paper trade order: %s @ %s", transaction_type, limit_price)
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
            raise OrderManagerError(f"Dhan order failed: {remarks}", status_code=502)

        data = response.get("data") or {}
        order_id = data.get("orderId") or data.get("order_id")
        if not order_id:
            raise OrderManagerError("Dhan response missing order_id", status_code=502)

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


_order_manager: OrderManager | None = None


def get_order_manager() -> OrderManager:
    """Return the shared order manager."""
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager()
    return _order_manager
