"""FastAPI application for the SRP Long Straddle Supertrend Confirmation bot."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from core.bot import get_trading_bot
from core.config_loader import ConfigError, get_config_loader
from core.dhan_client import reset_dhan_client
from core.logger import get_log_file_path, latest_log_file, setup_logger
from core.order_manager import OrderManagerError
from core.position_manager import get_bot_state

logger = setup_logger(console=False)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
        state.strategy_name = str(
            loader.get_strategy_config().get(
                "name", "Long Straddle Supertrend Confirmation"
            )
        )
        state.underlying = str(trading.get("underlying", ""))
        state.poll_interval = loader.get_polling_seconds()
        logger.info("SRP Long Straddle Supertrend Confirmation bot started")
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
    logger.info("SRP Long Straddle Supertrend Confirmation bot stopped")


app = FastAPI(
    title="SRP Dhan Long Straddle Supertrend Confirmation Bot",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(ConfigError)
async def config_error_handler(_: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})


@app.exception_handler(OrderManagerError)
async def order_manager_error_handler(_: Request, exc: OrderManagerError) -> JSONResponse:
    logger.error("Order manager error: %s", exc.message)
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
    """Root / health info endpoint."""
    loader = get_config_loader()
    return {
        "name": "SRP Dhan Long Straddle Supertrend Confirmation Bot",
        "status": get_bot_state().bot_status,
        "port": loader.get_port(),
        "endpoints": [
            "/",
            "/health",
            "/status",
            "/config",
            "/positions",
            "/orders",
            "/pnl",
            "/logs",
            "/stop",
        ],
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
    snapshot["trail"] = loader.get_trail_config()
    snapshot["supertrend"] = loader.get_supertrend_config()
    return snapshot


@app.get("/config")
async def config() -> dict[str, Any]:
    """Return loaded config summary (credentials redacted)."""
    loader = get_config_loader()
    summary = loader.summary()
    return {"status": "ok", "config": summary}


@app.get("/positions")
async def positions() -> dict[str, Any]:
    return {"status": "ok", "positions": get_bot_state().positions_dict()}


@app.get("/orders")
async def orders() -> dict[str, Any]:
    return {"status": "ok", "orders": get_bot_state().orders_list()}


@app.get("/pnl")
async def pnl() -> dict[str, Any]:
    return {"status": "ok", "pnl": get_bot_state().pnl_dict()}


@app.get("/logs")
async def logs(lines: int = 100) -> PlainTextResponse:
    """Return the last N lines of today's (or latest) bot log."""
    log_file = get_log_file_path()
    if not log_file.exists():
        log_file = latest_log_file()
    if not log_file.exists():
        return PlainTextResponse("No logs yet.")
    try:
        content = log_file.read_text(encoding="utf-8").splitlines()
        tail = content[-max(1, min(lines, 2000)) :]
        return PlainTextResponse("\n".join(tail))
    except Exception as exc:
        return PlainTextResponse(f"Failed to read logs: {exc}", status_code=500)


@app.post("/stop")
async def stop() -> dict[str, Any]:
    """Request graceful strategy stop and square-off."""
    bot = get_trading_bot()
    bot.stop()
    return {"status": "ok", "message": "Bot stop requested"}
