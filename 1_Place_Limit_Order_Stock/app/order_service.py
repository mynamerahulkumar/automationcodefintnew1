"""Order placement service using Dhan_SRP."""

from __future__ import annotations

from typing import Any

import requests

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_client import get_dhan_client
from app.logger import get_logger
from app.utils import resolve_instrument

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
        risk = self.config_loader.get_risk_config()
        cloud = self.config_loader.get_cloud_config()
        dry_run = bool(cloud.get("dry_run", False))

        quantity = int(trading["quantity"])
        limit_price = float(trading["limit_price"])
        transaction_type = str(trading.get("transaction_type", "BUY")).upper()
        product_type = str(trading.get("product_type", "INTRADAY")).upper()
        validity = str(trading.get("validity", "DAY")).upper()
        stock_name = str(trading.get("stock_name", ""))

        logger.info(
            "Placing order: segment=%s symbol=%s qty=%s price=%s dry_run=%s",
            trading.get("segment"),
            stock_name,
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
                    "Dhan authentication failed. Check DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env.",
                    status_code=401,
                ) from exc
            if "invalid syntax" in message.lower() or "match/case" in message.lower():
                raise OrderServiceError(
                    f"Python too old for dhanhq 2.2 ({message}). "
                    "Use Python 3.10+ — on EC2 install python3.11, recreate venv, "
                    "then: pip install -r requirements.txt",
                    status_code=500,
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
                "status": "dry_run",
                "security_id": instrument["security_id"],
                "symbol": instrument.get("trading_symbol", stock_name),
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
            "risk": risk_payload,
        }


_order_service: OrderService | None = None


def get_order_service() -> OrderService:
    """Return the shared order service instance."""
    global _order_service
    if _order_service is None:
        _order_service = OrderService()
    return _order_service
