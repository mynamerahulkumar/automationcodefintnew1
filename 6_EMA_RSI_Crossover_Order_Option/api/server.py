"""FastAPI server for the SRP Dhan EMA/RSI Trading Bot."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from core.config_loader import ConfigError, get_config_loader, source_label
from core.dhan_client import reset_dhan_client
from core.logger import LOG_FILE, get_logger, setup_logger
from core.order_manager import OrderManagerError
from core.signal_engine import get_signal_engine

logger = get_logger()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Load config, resolve security_id, and start the signal engine."""
    engine = get_signal_engine()
    try:
        loader = get_config_loader()
        loader.load()
        log_cfg = loader.get_logging_config()
        setup_logger(
            str(log_cfg.get("level", "INFO")),
            console=os.environ.get("LOG_CONSOLE", "").lower() in {"1", "true", "yes"},
        )
        market = loader.get_market_config()
        instrument = loader.get_resolved_instrument()
        engine._sync_state_from_config()
        logger.info("SRP Dhan Trading Bot started")
        logger.info(
            "Resolved %s -> security_id %s from %s",
            market.get("trading_symbol"),
            instrument["security_id"],
            source_label(str(instrument.get("source", "csv"))),
        )
        engine.start()
    except ConfigError as exc:
        logger.error("Startup config error: %s", exc)
    except Exception:
        logger.exception("Startup failed")
    yield
    engine.stop()
    reset_dhan_client()
    logger.info("SRP Dhan Trading Bot stopped")


app = FastAPI(title="SRP Dhan EMA/RSI Trading Bot", version="1.0.0", lifespan=lifespan)


@app.exception_handler(ConfigError)
async def config_error_handler(_: Request, exc: ConfigError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})


@app.exception_handler(OrderManagerError)
async def order_error_handler(_: Request, exc: OrderManagerError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.message},
    )


@app.exception_handler(Exception)
async def generic_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API exception")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": str(exc)},
    )


@app.get("/")
async def root() -> dict[str, Any]:
    """Bot info and running status."""
    state = get_signal_engine().state.snapshot()
    return {
        "name": "SRP Dhan EMA/RSI Trading Bot",
        "version": "1.0.0",
        "running": state["running"],
        "strategy": state["strategy_mode"],
        "symbol": state["symbol"],
    }


@app.get("/health")
async def health() -> PlainTextResponse:
    """Health check endpoint."""
    return PlainTextResponse("Running")


@app.get("/status")
async def status() -> dict[str, Any]:
    """Return bot status, indicators, position, and resource usage."""
    loader = get_config_loader()
    snapshot = get_signal_engine().state.snapshot()
    snapshot["risk"] = loader.get_risk_config()
    snapshot["paper_trade"] = bool(loader.get_trade_config().get("paper_trade", False))
    return snapshot


@app.get("/config")
async def config() -> dict[str, Any]:
    """Return safe configuration summary."""
    return {"status": "ok", "config": get_config_loader().summary()}


@app.get("/logs")
async def logs(lines: int = Query(default=100, ge=1, le=1000)) -> dict[str, Any]:
    """Return the last N lines from trading.log."""
    log_path = Path(LOG_FILE)
    if not log_path.exists():
        return {"status": "ok", "lines": [], "count": 0}

    content = log_path.read_text(encoding="utf-8").splitlines()
    tail = content[-lines:]
    return {"status": "ok", "lines": tail, "count": len(tail)}


@app.get("/strategy")
async def strategy() -> dict[str, Any]:
    """Return active strategy configuration and latest signal."""
    loader = get_config_loader()
    state = get_signal_engine().state.snapshot()
    return {
        "mode": loader.get_strategy_mode(),
        "timeframe": loader.get_strategy_config().get("timeframe"),
        "ema": loader.get_ema_config(),
        "rsi": loader.get_rsi_config(),
        "signal": state["signal"],
        "ema_fast": state["ema_fast"],
        "ema_slow": state["ema_slow"],
        "rsi": state["rsi"],
    }


@app.post("/start")
async def start_engine() -> dict[str, Any]:
    """Start the polling engine if stopped."""
    engine = get_signal_engine()
    if engine.state.running and engine.scheduler.is_running:
        return {"status": "already_running"}
    engine.start()
    return {"status": "started"}


@app.post("/stop")
async def stop_engine() -> dict[str, Any]:
    """Stop the polling engine gracefully."""
    engine = get_signal_engine()
    engine.stop()
    return {"status": "stopped"}
