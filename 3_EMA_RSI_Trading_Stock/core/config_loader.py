"""Load, validate YAML configuration and resolve security IDs from CSV."""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

import yaml

from core.logger import get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
SECURITY_MASTER_PATH = PROJECT_ROOT / "security_id" / "api-scrip-master.csv"

logger = get_logger()

TIMEFRAME_PATTERN = re.compile(r"^(\d+)(m|min|minute|h|hour|d|day)?$", re.IGNORECASE)
VALID_MODES = {"EMA", "RSI", "EMA_RSI"}

_EQUITY_INDEX: dict[tuple[str, str], dict[str, Any]] | None = None
_OPTION_CACHE: dict[tuple[str, str, str, float, str], dict[str, Any]] = {}


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


def get_security_master_path() -> Path:
    """Return path to the security master CSV."""
    return SECURITY_MASTER_PATH


def exchange_segment(exchange: str, segment: str) -> str:
    """Map exchange and segment to Dhan exchange_segment."""
    exchange = exchange.upper()
    segment = segment.upper()
    if segment in {"EQUITY", "STOCK"}:
        return "NSE_EQ" if exchange == "NSE" else "BSE_EQ"
    if segment in {"OPTION", "FNO"}:
        return "NSE_FNO" if exchange == "NSE" else "BSE_FNO"
    raise ValueError(f"Unsupported segment: {segment}")


def build_equity_index() -> dict[tuple[str, str], dict[str, Any]]:
    """Stream CSV once and build a compact equity symbol index."""
    global _EQUITY_INDEX
    if _EQUITY_INDEX is not None:
        return _EQUITY_INDEX

    if not SECURITY_MASTER_PATH.exists():
        raise FileNotFoundError(f"Security master not found: {SECURITY_MASTER_PATH}")

    index: dict[tuple[str, str], dict[str, Any]] = {}
    logger.info("Building equity index from %s", SECURITY_MASTER_PATH.name)

    with open(SECURITY_MASTER_PATH, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("SEM_INSTRUMENT_NAME") != "EQUITY":
                continue
            exch = str(row.get("SEM_EXM_EXCH_ID", "")).upper()
            symbol = str(row.get("SEM_TRADING_SYMBOL", "")).upper()
            if not exch or not symbol:
                continue
            key = (exch, symbol)
            if key in index:
                continue
            index[key] = {
                "security_id": str(row["SEM_SMST_SECURITY_ID"]),
                "trading_symbol": str(row["SEM_TRADING_SYMBOL"]),
                "exchange_segment": exchange_segment(exch, "EQUITY"),
                "instrument_name": "EQUITY",
            }

    _EQUITY_INDEX = index
    logger.info("Equity index ready with %s symbols", len(index))
    return index


def resolve_equity_security(
    stock_name: str,
    exchange: str = "NSE",
    security_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an equity security from symbol or explicit security_id."""
    seg = exchange_segment(exchange, "EQUITY")

    if security_id:
        return {
            "security_id": str(security_id),
            "trading_symbol": stock_name.upper(),
            "exchange_segment": seg,
            "instrument_name": "EQUITY",
        }

    index = build_equity_index()
    key = (exchange.upper(), stock_name.upper().strip())
    resolved = index.get(key)
    if resolved is None:
        raise ValueError(f"Security ID not found for stock: {stock_name} on {exchange}")

    logger.info("Resolved equity %s -> security_id %s", stock_name, resolved["security_id"])
    return resolved.copy()


def resolve_option_security(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
    exchange: str = "NSE",
    security_id: str | None = None,
) -> dict[str, Any]:
    """Resolve an option contract by streaming the CSV (cached after first match)."""
    seg = exchange_segment(exchange, "OPTION")

    if security_id:
        return {
            "security_id": str(security_id),
            "trading_symbol": f"{underlying} {int(strike)} {option_type}",
            "exchange_segment": seg,
            "instrument_name": "OPTIDX",
            "lot_size": None,
        }

    cache_key = (
        exchange.upper(),
        underlying.upper(),
        str(expiry),
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
                "exchange_segment": seg,
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


def resolve_instrument(market_config: dict[str, Any]) -> dict[str, Any]:
    """Resolve instrument details from market configuration."""
    instrument = str(market_config.get("instrument", "STOCK")).upper()
    exchange = str(market_config.get("exchange", "NSE")).upper()
    trading_symbol = str(market_config.get("trading_symbol", "")).strip()
    security_id = market_config.get("security_id") or None
    if security_id == "":
        security_id = None

    if instrument == "STOCK":
        return resolve_equity_security(
            stock_name=trading_symbol,
            exchange=exchange,
            security_id=str(security_id) if security_id else None,
        )

    return resolve_option_security(
        underlying=trading_symbol,
        expiry=str(market_config["expiry"]),
        strike=float(market_config["strike"]),
        option_type=str(market_config["option_type"]),
        exchange=exchange,
        security_id=str(security_id) if security_id else None,
    )


class ConfigLoader:
    """Loads, validates, and provides access to application configuration."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict[str, Any] = {}
        self._resolved_instrument: dict[str, Any] | None = None

    @property
    def config(self) -> dict[str, Any]:
        if not self._config:
            self.load()
        return self._config

    def load(self) -> dict[str, Any]:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise ConfigError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)

        if not raw or not isinstance(raw, dict):
            raise ConfigError("Configuration file is empty or invalid")

        self._validate(raw)
        self._config = raw
        self._resolved_instrument = None
        logger.info("Configuration loaded from %s", self.config_path)
        return self._config

    def reload(self) -> dict[str, Any]:
        """Reload configuration from disk."""
        return self.load()

    def get_broker_credentials(self) -> tuple[str, str]:
        """Return Dhan credentials with environment overrides."""
        broker = self.config.get("broker", {})
        client_id = os.environ.get("DHAN_CLIENT_ID") or broker.get("client_id", "")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN") or broker.get("access_token", "")

        if not client_id or not access_token:
            raise ConfigError(
                "Broker credentials missing. Set broker.client_id and broker.access_token "
                "in config or DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN env vars."
            )
        return str(client_id), str(access_token)

    def get_market_config(self) -> dict[str, Any]:
        """Return the market section."""
        market = self.config.get("market")
        if not market or not isinstance(market, dict):
            raise ConfigError("market section is missing from configuration")
        return market

    def get_strategy_config(self) -> dict[str, Any]:
        """Return the strategy section."""
        strategy = self.config.get("strategy")
        if not strategy or not isinstance(strategy, dict):
            raise ConfigError("strategy section is missing from configuration")
        return strategy

    def get_ema_config(self) -> dict[str, Any]:
        """Return EMA parameters."""
        return self.config.get("ema", {})

    def get_rsi_config(self) -> dict[str, Any]:
        """Return RSI parameters."""
        return self.config.get("rsi", {})

    def get_trade_config(self) -> dict[str, Any]:
        """Return trade parameters."""
        trade = self.config.get("trade")
        if not trade or not isinstance(trade, dict):
            raise ConfigError("trade section is missing from configuration")
        return trade

    def get_risk_config(self) -> dict[str, Any]:
        """Return risk parameters."""
        return self.config.get("risk", {})

    def get_logging_config(self) -> dict[str, Any]:
        """Return logging parameters."""
        return self.config.get("logging", {})

    def get_strategy_mode(self) -> str:
        """Return active strategy mode."""
        return str(self.get_strategy_config().get("mode", "EMA")).upper()

    def get_polling_seconds(self) -> int:
        """Return configured polling interval."""
        polling = self.config.get("polling", {})
        return int(polling.get("seconds", 30))

    def get_startup_poll_logs(self) -> int:
        """Return number of poll summaries to stream on CLI at startup."""
        polling = self.config.get("polling", {})
        return int(polling.get("startup_poll_logs", 3))

    def parse_timeframe_minutes(self) -> int:
        """Convert strategy.timeframe (e.g. 5m) to minutes for Dhan API."""
        raw = str(self.get_strategy_config().get("timeframe", "5m")).strip()
        match = TIMEFRAME_PATTERN.match(raw)
        if not match:
            raise ConfigError(f"Invalid strategy.timeframe: {raw}")

        value = int(match.group(1))
        unit = (match.group(2) or "m").lower()

        if unit in {"m", "min", "minute"}:
            return value
        if unit in {"h", "hour"}:
            return value * 60
        if unit in {"d", "day"}:
            raise ConfigError("DAY timeframe not supported for intraday polling")
        raise ConfigError(f"Invalid strategy.timeframe unit: {raw}")

    def get_trading_config(self) -> dict[str, Any]:
        """Return normalized trading config for order/market modules."""
        market = self.get_market_config()
        trade = self.get_trade_config()
        instrument = str(market.get("instrument", "STOCK")).upper()
        segment = "EQUITY" if instrument == "STOCK" else "OPTION"

        return {
            "exchange": str(market.get("exchange", "NSE")),
            "segment": segment,
            "instrument": instrument,
            "stock_name": str(market.get("trading_symbol", "")),
            "trading_symbol": str(market.get("trading_symbol", "")),
            "security_id": market.get("security_id", ""),
            "expiry": market.get("expiry", ""),
            "strike": market.get("strike", ""),
            "option_type": market.get("option_type", ""),
            "quantity": int(trade.get("quantity", 1)),
            "order_type": str(trade.get("order_type", "LIMIT")).upper(),
            "product_type": str(trade.get("product_type", "CNC")).upper(),
            "transaction_type": str(trade.get("transaction_type", "BUY")).upper(),
            "limit_buffer": float(trade.get("limit_buffer", 0.10)),
            "paper_trade": bool(trade.get("paper_trade", False)),
            "validity": str(trade.get("validity", "DAY")).upper(),
        }

    def get_resolved_instrument(self) -> dict[str, Any]:
        """Resolve and cache security_id from CSV."""
        if self._resolved_instrument is None:
            self._resolved_instrument = resolve_instrument(self.get_market_config())
        return self._resolved_instrument

    def summary(self) -> dict[str, Any]:
        """Return a safe summary without raw tokens."""
        market = self.get_market_config()
        strategy = self.get_strategy_config()
        trade = self.get_trade_config()
        risk = self.get_risk_config()
        ema = self.get_ema_config()
        rsi = self.get_rsi_config()

        instrument = self.get_resolved_instrument() if self._config else {}
        return {
            "broker": "DHAN",
            "market": {
                "exchange": market.get("exchange"),
                "instrument": market.get("instrument"),
                "trading_symbol": market.get("trading_symbol"),
                "security_id": instrument.get("security_id", market.get("security_id")),
            },
            "strategy": {
                "mode": strategy.get("mode"),
                "timeframe": strategy.get("timeframe"),
            },
            "ema": ema,
            "rsi": rsi,
            "trade": {
                "quantity": trade.get("quantity"),
                "order_type": trade.get("order_type"),
                "product_type": trade.get("product_type"),
                "limit_buffer": trade.get("limit_buffer"),
                "paper_trade": trade.get("paper_trade", False),
            },
            "risk": risk,
            "polling_seconds": self.get_polling_seconds(),
            "startup_poll_logs": self.get_startup_poll_logs(),
        }

    def _validate(self, raw: dict[str, Any]) -> None:
        """Validate required configuration fields."""
        market = raw.get("market")
        if not market or not isinstance(market, dict):
            raise ConfigError("market section is required")

        if not market.get("trading_symbol"):
            raise ConfigError("market.trading_symbol is required")

        instrument = str(market.get("instrument", "STOCK")).upper()
        if instrument not in {"STOCK", "OPTION"}:
            raise ConfigError("market.instrument must be STOCK or OPTION")

        if instrument == "OPTION":
            for field in ("expiry", "strike", "option_type"):
                if market.get(field) in (None, ""):
                    raise ConfigError(f"market.{field} is required for OPTION instrument")

        strategy = raw.get("strategy")
        if not strategy or not isinstance(strategy, dict):
            raise ConfigError("strategy section is required")

        mode = str(strategy.get("mode", "")).upper()
        if mode not in VALID_MODES:
            raise ConfigError(f"strategy.mode must be one of: {', '.join(sorted(VALID_MODES))}")

        ema = raw.get("ema", {})
        fast = int(ema.get("fast", 9))
        slow = int(ema.get("slow", 21))
        if mode in {"EMA", "EMA_RSI"} and fast >= slow:
            raise ConfigError("ema.fast must be less than ema.slow")

        rsi = raw.get("rsi", {})
        if mode in {"RSI", "EMA_RSI"}:
            buy_level = float(rsi.get("buy", 60))
            sell_level = float(rsi.get("sell", 40))
            if buy_level <= sell_level:
                raise ConfigError("rsi.buy must be greater than rsi.sell")

        trade = raw.get("trade")
        if not trade or not isinstance(trade, dict):
            raise ConfigError("trade section is required")

        order_type = str(trade.get("order_type", "LIMIT")).upper()
        if order_type != "LIMIT":
            raise ConfigError("Only LIMIT orders are supported")

        quantity = trade.get("quantity")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ConfigError("trade.quantity must be a positive integer")

        polling = raw.get("polling", {})
        seconds = int(polling.get("seconds", 30))
        if seconds < 10:
            raise ConfigError("polling.seconds must be at least 10")

        startup_poll_logs = int(polling.get("startup_poll_logs", 3))
        if startup_poll_logs < 0:
            raise ConfigError("polling.startup_poll_logs must be 0 or greater")
        if 0 < startup_poll_logs < 3:
            raise ConfigError("polling.startup_poll_logs must be at least 3 (or 0 to skip)")

        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = raw
        loader.parse_timeframe_minutes()


_config_loader: ConfigLoader | None = None


def get_config_loader(config_path: Path | str | None = None) -> ConfigLoader:
    """Return the shared configuration loader."""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)
    return _config_loader
