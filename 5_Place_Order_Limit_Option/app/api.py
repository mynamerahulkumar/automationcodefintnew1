"""FastAPI application for Dhan limit order placement."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config_loader import ConfigError, get_config_loader
from app.dhan_client import reset_dhan_client
from app.logger import setup_logger
from app.order_service import OrderServiceError, get_order_service
from app.utils import get_security_master_path

logger = setup_logger(console=False)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load config and resolve security_id from CSV at startup."""
    try:
        loader = get_config_loader()
        loader.load()
        cloud = loader.get_cloud_config()
        setup_logger(
            str(cloud.get("log_level", "INFO")),
            console=bool(cloud.get("console_log", False))
            or os.environ.get("LOG_CONSOLE", "").lower() in {"1", "true", "yes"},
        )
        trading = loader.get_trading_config()
        instrument = loader.get_resolved_instrument()
        logger.info("Dhan Limit Order API started")
        logger.info(
            "Resolved %s -> security_id %s from %s",
            trading.get("stock_name"),
            instrument["security_id"],
            get_security_master_path().name,
        )
    except ConfigError as exc:
        logger.error("Startup config error: %s", exc)
    yield
    logger.info("Dhan Limit Order API stopped")


app = FastAPI(title="Dhan Limit Order API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(ConfigError)
async def config_error_handler(_: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})


@app.exception_handler(OrderServiceError)
async def order_service_error_handler(_: Request, exc: OrderServiceError) -> JSONResponse:
    logger.error("Order service error: %s", exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.message},
    )


@app.exception_handler(Exception)
async def generic_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "running"}


@app.get("/config")
async def get_config() -> dict[str, Any]:
    """Return loaded config with security_id resolved from CSV."""
    loader = get_config_loader()
    trading = loader.get_trading_config()
    instrument = loader.get_resolved_instrument()
    return {
        "status": "ok",
        "security_master": str(get_security_master_path()),
        "trading": loader.summary(),
        "resolved": {
            "security_id": instrument["security_id"],
            "trading_symbol": instrument["trading_symbol"],
            "exchange_segment": instrument["exchange_segment"],
            "instrument_name": instrument["instrument_name"],
        },
    }


@app.post("/place-order")
async def place_order() -> dict[str, Any]:
    """Place a LIMIT order using values from config.yaml."""
    logger.info("POST /place-order")
    return get_order_service().place_order_from_config()


@app.post("/reload-config")
async def reload_config() -> dict[str, Any]:
    """Reload configuration without restarting the server."""
    logger.info("POST /reload-config")
    reset_dhan_client()
    summary = get_order_service().reload_config()
    cloud = get_config_loader().get_cloud_config()
    setup_logger(
        str(cloud.get("log_level", "INFO")),
        console=bool(cloud.get("console_log", False)),
    )
    return {"status": "success", "config": summary}
