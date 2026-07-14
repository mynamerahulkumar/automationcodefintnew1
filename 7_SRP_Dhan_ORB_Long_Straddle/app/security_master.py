"""Lightweight security master lookups using stdlib csv."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.logger import get_logger
from app.utils import INDEX_SECURITY_IDS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECURITY_MASTER_PATH = PROJECT_ROOT / "security_id" / "api-scrip-master.csv"

logger = get_logger()

_OPTION_CACHE: dict[tuple[str, str, str, float, str], dict[str, Any]] = {}
_INDEX_CACHE: dict[str, dict[str, Any]] | None = None


def get_security_master_path() -> Path:
    return SECURITY_MASTER_PATH


def exchange_segment_fno(exchange: str) -> str:
    return "NSE_FNO" if exchange.upper() == "NSE" else "BSE_FNO"


def get_underlying_security_id(underlying: str, configured: str | None = None) -> int:
    """Return index/underlying security id for option-chain helpers."""
    if configured not in (None, ""):
        return int(configured)
    key = underlying.upper().strip()
    if key in INDEX_SECURITY_IDS:
        return INDEX_SECURITY_IDS[key]
    raise ValueError(f"Unknown underlying security id for {underlying}")


def _normalize_expiry(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        return raw
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw[:19] if " " in raw else raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw[:10]


def resolve_option_security(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
    exchange: str = "NSE",
    security_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an option contract from api-scrip-master.csv (cached)."""
    seg = exchange_segment_fno(exchange)

    if security_id:
        return {
            "security_id": str(security_id),
            "trading_symbol": f"{underlying} {int(strike)} {option_type}",
            "exchange_segment": seg,
            "instrument_name": "OPTIDX",
            "lot_size": None,
            "expiry": expiry,
            "strike": float(strike),
            "option_type": option_type.upper(),
        }

    expiry_norm = _normalize_expiry(expiry)
    cache_key = (
        exchange.upper(),
        underlying.upper(),
        expiry_norm,
        float(strike),
        option_type.upper(),
    )
    if cache_key in _OPTION_CACHE:
        return _OPTION_CACHE[cache_key].copy()

    if not SECURITY_MASTER_PATH.exists():
        raise FileNotFoundError(f"Security master not found: {SECURITY_MASTER_PATH}")

    underlying_upper = underlying.upper()
    symbol_prefix = f"{underlying_upper}-"
    custom_prefix = f"{underlying_upper} "
    exchange_upper = exchange.upper()
    option_upper = option_type.upper()
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

            row_expiry = _normalize_expiry(str(row.get("SEM_EXPIRY_DATE", "")))
            if row_expiry != expiry_norm:
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
                "custom_symbol": str(row.get("SEM_CUSTOM_SYMBOL", "")),
                "exchange_segment": seg,
                "instrument_name": str(row["SEM_INSTRUMENT_NAME"]),
                "lot_size": int(float(lot_units)) if lot_units else None,
                "expiry": row_expiry,
                "strike": strike_val,
                "option_type": option_upper,
            }
            _OPTION_CACHE[cache_key] = resolved.copy()
            logger.info(
                "Resolved option %s %s %s %s -> security_id %s",
                underlying,
                expiry_norm,
                strike,
                option_type,
                resolved["security_id"],
            )
            return resolved

    raise ValueError(
        f"Option contract not found: {underlying} {strike} {option_type} {expiry_norm}"
    )


def list_option_expiries(underlying: str, exchange: str = "NSE") -> list[str]:
    """Return sorted unique upcoming option expiry dates (YYYY-MM-DD) from CSV."""
    if not SECURITY_MASTER_PATH.exists():
        raise FileNotFoundError(f"Security master not found: {SECURITY_MASTER_PATH}")

    underlying_upper = underlying.upper()
    symbol_prefix = f"{underlying_upper}-"
    custom_prefix = f"{underlying_upper} "
    exchange_upper = exchange.upper()
    today = date.today().isoformat()
    expiries: set[str] = set()

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
            expiry = _normalize_expiry(str(row.get("SEM_EXPIRY_DATE", "")))
            if expiry and expiry >= today:
                expiries.add(expiry)

    return sorted(expiries)


def resolve_weekly_expiry(underlying: str, exchange: str = "NSE") -> str:
    """Resolve nearest upcoming weekly expiry date string."""
    expiries = list_option_expiries(underlying, exchange)
    if not expiries:
        raise ValueError(f"No upcoming expiries found for {underlying}")
    return expiries[0]


def resolve_expiry(expiry_cfg: str, underlying: str, exchange: str = "NSE") -> str:
    """Resolve WEEKLY / blank / concrete expiry to YYYY-MM-DD."""
    raw = str(expiry_cfg or "").strip().upper()
    if raw in {"", "WEEKLY", "WEEK", "NEAR", "CURRENT"}:
        return resolve_weekly_expiry(underlying, exchange)
    return _normalize_expiry(expiry_cfg)
