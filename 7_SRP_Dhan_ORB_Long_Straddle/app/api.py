"""FastAPI application for the SRP Long Straddle ORB bot."""

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
from app.order_service import OrderServiceError
from app.state import get_bot_state

logger = setup_logger(console=False)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load config and start the trading bot."""
    bot = get_trading_bot()
    try:
        loader = get_config_loader()
        loader.load()
        log_cfg = loader.get_logging_config()
        setup_logger(
            str(log_cfg.get("level", "INFO")),
            console=os.environ.get("LOG_CONSOLE", "").lower() in {"1", "true", "yes"}
            or bool(log_cfg.get("console", False)),
        )
        trading = loader.get_trading_config()
        state = get_bot_state()
        state.strategy_name = str(loader.get_strategy_config().get("name", "Long Straddle ORB"))
        state.underlying = str(trading.get("underlying", ""))
        state.poll_interval = loader.get_polling_seconds()
        logger.info("SRP Long Straddle ORB bot started")
        logger.info(
            "Mode=%s underlying=%s polling=%ss port=%s",
            "PAPER" if loader.is_paper_trade() else "LIVE",
            trading.get("underlying"),
            loader.get_polling_seconds(),
            loader.get_port(),
        )
        bot.start()
    except ConfigError as exc:
        logger.error("Startup config error: %s", exc)
    except Exception:
        logger.exception("Startup failed")
    yield
    bot.stop()
    reset_dhan_client()
    logger.info("SRP Long Straddle ORB bot stopped")


app = FastAPI(
    title="SRP Dhan Long Straddle ORB Bot",
    version="1.0.0",
    lifespan=lifespan,
)


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


@app.get("/")
async def root() -> dict[str, Any]:
    """Root info endpoint."""
    loader = get_config_loader()
    return {
        "name": "SRP Dhan Long Straddle ORB Bot",
        "status": get_bot_state().bot_status,
        "port": loader.get_port(),
        "endpoints": ["/", "/health", "/status", "/config"],
    }


@app.get("/health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("Running")


@app.get("/status")
async def status() -> dict[str, Any]:
    loader = get_config_loader()
    snapshot = get_bot_state().snapshot()
    snapshot["paper_trade"] = loader.is_paper_trade()
    snapshot["risk"] = loader.get_risk_config()
    return snapshot


@app.get("/config")
async def config() -> dict[str, Any]:
    """Return loaded config summary (credentials redacted)."""
    loader = get_config_loader()
    summary = loader.summary()
    return {"status": "ok", "config": summary}
