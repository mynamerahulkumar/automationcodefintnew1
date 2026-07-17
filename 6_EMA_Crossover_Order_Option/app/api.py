"""FastAPI application for the SRP EMA Crossover Trading Engine."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.bot import get_trading_bot
from app.config_loader import ConfigError, get_config_loader
from app.dhan_client import reset_dhan_client
from app.logger import setup_logger
from app.order_service import OrderServiceError, get_order_service
from app.security_master import build_equity_index, get_security_master_path
from app.state import get_bot_state

logger = setup_logger(console=False)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load config, resolve security_id, and start the trading bot."""
    bot = get_trading_bot()
    try:
        loader = get_config_loader()
        loader.load()
        bot_cfg = loader.get_bot_config()
        setup_logger(
            str(bot_cfg.get("log_level", "INFO")),
            console=os.environ.get("LOG_CONSOLE", "").lower() in {"1", "true", "yes"},
        )
        trading = loader.get_trading_config()
        if not str(trading.get("security_id") or "").strip():
            build_equity_index()
        instrument = loader.get_resolved_instrument()
        state = get_bot_state()
        state.strategy_name = str(loader.get_strategy_config().get("name", "EMA_CROSSOVER"))
        state.symbol = str(trading.get("stock_name", ""))
        state.security_id = str(instrument["security_id"])
        state.poll_interval = loader.get_polling_seconds()
        logger.info("SRP Trading Engine started")
        logger.info(
            "Resolved %s -> security_id %s from %s",
            trading.get("stock_name"),
            instrument["security_id"],
            get_security_master_path().name
            if not str(trading.get("security_id") or "").strip()
            else "config.yaml",
        )
        bot.start()
    except ConfigError as exc:
        logger.error("Startup config error: %s", exc)
    except Exception:
        logger.exception("Startup failed")
    yield
    bot.stop()
    reset_dhan_client()
    logger.info("SRP Trading Engine stopped")


app = FastAPI(title="SRP EMA Crossover Trading Engine", version="1.0.0", lifespan=lifespan)


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
async def health() -> PlainTextResponse:
    """Health check endpoint."""
    return PlainTextResponse("Running")


@app.get("/status")
async def status() -> dict[str, Any]:
    """Return bot status, strategy info, and last trade details."""
    loader = get_config_loader()
    bot_cfg = loader.get_bot_config()
    risk = loader.get_risk_config()
    snapshot = get_bot_state().snapshot()
    snapshot["paper_trade"] = bool(bot_cfg.get("paper_trade", False))
    snapshot["risk"] = {
        "target_percent": risk.get("target_percent"),
        "stoploss_percent": risk.get("stoploss_percent"),
        "trailing_sl": risk.get("trailing_sl", False),
    }
    return snapshot


@app.post("/reload-config")
async def reload_config() -> dict[str, Any]:
    """Reload YAML configuration without restarting the server."""
    logger.info("POST /reload-config")
    reset_dhan_client()
    summary = get_order_service().reload_config()
    bot = get_trading_bot()
    bot.reload()
    bot_cfg = get_config_loader().get_bot_config()
    setup_logger(str(bot_cfg.get("log_level", "INFO")))
    return {"status": "success", "config": summary}


@app.post("/place-order")
async def place_order() -> dict[str, Any]:
    """Place a manual LIMIT order using values from config.yaml."""
    logger.info("POST /place-order")
    return get_order_service().place_order_from_config()
