"""Lightweight security master lookups using stdlib csv (no pandas duplicate load)."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from app.logger import get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECURITY_MASTER_PATH = PROJECT_ROOT / "security_id" / "api-scrip-master.csv"

logger = get_logger()

_OPTION_CACHE: dict[tuple[str, str, str, float, str], dict[str, Any]] = {}


def get_security_master_path() -> Path:
    """Return the path to the local security master CSV."""
    return SECURITY_MASTER_PATH


def _exchange_segment(exchange: str, segment: str) -> str:
    """Map exchange and segment to Dhan exchange_segment."""
    exchange = exchange.upper()
    segment = segment.upper()
    if segment == "EQUITY":
        return "NSE_EQ" if exchange == "NSE" else "BSE_EQ"
    if segment == "OPTION":
        return "NSE_FNO" if exchange == "NSE" else "BSE_FNO"
    raise ValueError(f"Unsupported segment: {segment}")


def _lookup_equity_from_csv(stock_name: str, exchange: str) -> dict[str, Any]:
    """
    Stream api-scrip-master.csv until the first matching equity row.

    Avoids loading the full ~20k-symbol index into memory (important on 1GB hosts).
    """
    if not SECURITY_MASTER_PATH.exists():
        raise FileNotFoundError(f"Security master not found: {SECURITY_MASTER_PATH}")

    exchange_upper = exchange.upper()
    symbol_upper = stock_name.upper().strip()
    logger.info(
        "Streaming CSV lookup for %s on %s (low-memory mode)",
        symbol_upper,
        exchange_upper,
    )

    with open(SECURITY_MASTER_PATH, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("SEM_INSTRUMENT_NAME") != "EQUITY":
                continue
            if str(row.get("SEM_EXM_EXCH_ID", "")).upper() != exchange_upper:
                continue
            if str(row.get("SEM_TRADING_SYMBOL", "")).upper() != symbol_upper:
                continue
            return {
                "security_id": str(row["SEM_SMST_SECURITY_ID"]),
                "trading_symbol": str(row["SEM_TRADING_SYMBOL"]),
                "exchange_segment": _exchange_segment(exchange_upper, "EQUITY"),
                "instrument_name": "EQUITY",
            }

    raise ValueError(f"Security ID not found for stock: {stock_name} on {exchange}")


def resolve_equity_security(
    stock_name: str,
    exchange: str = "NSE",
    security_id: str | None = None,
) -> dict[str, Any]:
    """
    Resolve an equity security.

    Prefer non-blank config security_id and skip CSV entirely (low RAM).
    If config ID is missing, stream CSV for a single-symbol match.
    """
    exchange_segment = _exchange_segment(exchange, "EQUITY")
    config_id = str(security_id).strip() if security_id else ""

    if config_id:
        logger.info(
            "Using config security_id %s for %s (CSV lookup skipped)",
            config_id,
            stock_name,
        )
        return {
            "security_id": config_id,
            "trading_symbol": stock_name.upper(),
            "exchange_segment": exchange_segment,
            "instrument_name": "EQUITY",
        }

    resolved = _lookup_equity_from_csv(stock_name, exchange)
    logger.info("Resolved equity %s -> security_id %s", stock_name, resolved["security_id"])
    return resolved


def resolve_option_security(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
    exchange: str = "NSE",
    security_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an option contract by streaming the CSV (cached after first match)."""
    exchange_segment = _exchange_segment(exchange, "OPTION")

    if security_id:
        return {
            "security_id": str(security_id),
            "trading_symbol": f"{underlying} {int(strike)} {option_type}",
            "exchange_segment": exchange_segment,
            "instrument_name": "OPTIDX",
            "lot_size": None,
        }

    cache_key = (exchange.upper(), underlying.upper(), str(expiry), float(strike), option_type.upper())
    if cache_key in _OPTION_CACHE:
        return _OPTION_CACHE[cache_key].copy()

    if not SECURITY_MASTER_PATH.exists():
        raise FileNotFoundError(f"Security master not found: {SECURITY_MASTER_PATH}")

    underlying_upper = underlying.upper()
    symbol_prefix = f"{underlying_upper}-"
    custom_prefix = f"{underlying_upper} "
    exchange_upper = exchange.upper()
    option_upper = option_type.upper()
    expiry_str = str(expiry)
    strike_val = float(strike)

    with open(SECURITY_MASTER_PATH, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("SEM_INSTRUMENT_NAME") not in {"OPTIDX", "OPTSTK"}:
                continue
            if str(row.get("SEM_EXM_EXCH_ID", "")).upper() != exchange_upper:
                continue

            trading_symbol = str(row.get("SEM_TRADING_SYMBOL", "")).upper()
            custom_symbol = str(row.get("SEM_CUSTOM_SYMBOL", "")).upper()
            if not (
                trading_symbol.startswith(symbol_prefix)
                or custom_symbol.startswith(custom_prefix)
            ):
                continue
            if str(row.get("SEM_OPTION_TYPE", "")).upper() != option_upper:
                continue
            if str(row.get("SEM_EXPIRY_DATE", "")) != expiry_str:
                continue
            try:
                if float(row.get("SEM_STRIKE_PRICE", 0)) != strike_val:
                    continue
            except (TypeError, ValueError):
                continue

            lot_units = row.get("SEM_LOT_UNITS")
            resolved = {
                "security_id": str(row["SEM_SMST_SECURITY_ID"]),
                "trading_symbol": str(row["SEM_TRADING_SYMBOL"]),
                "exchange_segment": exchange_segment,
                "instrument_name": str(row["SEM_INSTRUMENT_NAME"]),
                "lot_size": int(float(lot_units)) if lot_units else None,
            }
            _OPTION_CACHE[cache_key] = resolved.copy()
            logger.info(
                "Resolved option %s %s %s -> security_id %s",
                underlying,
                strike,
                option_type,
                resolved["security_id"],
            )
            return resolved

    raise ValueError(
        f"Option contract not found: {underlying} {strike} {option_type} {expiry}"
    )


def resolve_instrument(trading_config: dict[str, Any]) -> dict[str, Any]:
    """Resolve instrument details from trading configuration."""
    segment = str(trading_config.get("segment", "EQUITY")).upper()
    exchange = str(trading_config.get("exchange", "NSE")).upper()
    stock_name = str(trading_config.get("stock_name", "")).strip()
    security_id = trading_config.get("security_id") or None
    if security_id == "":
        security_id = None

    if segment == "EQUITY":
        return resolve_equity_security(
            stock_name=stock_name,
            exchange=exchange,
            security_id=str(security_id) if security_id else None,
        )

    return resolve_option_security(
        underlying=stock_name,
        expiry=str(trading_config["expiry"]),
        strike=float(trading_config["strike"]),
        option_type=str(trading_config["option_type"]),
        exchange=exchange,
        security_id=str(security_id) if security_id else None,
    )
