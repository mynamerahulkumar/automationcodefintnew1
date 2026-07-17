"""Load and validate YAML configuration for Long Straddle Supertrend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from core.logger import get_logger
from core.utils import INDEX_SECURITY_IDS, parse_hhmm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

logger = get_logger()

_ENV_LOADED = False


def load_env_file(env_path: Path | None = None) -> Path | None:
    """Load project-root .env once (does not override existing env vars)."""
    global _ENV_LOADED
    path = env_path or DEFAULT_ENV_PATH
    if path.exists():
        load_dotenv(path, override=False)
        _ENV_LOADED = True
        return path
    load_dotenv(override=False)
    _ENV_LOADED = True
    return None


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


class ConfigLoader:
    """Loads, validates, and exposes application configuration."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict[str, Any] = {}

    @property
    def config(self) -> dict[str, Any]:
        if not self._config:
            self.load()
        return self._config

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise ConfigError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)

        if not raw or not isinstance(raw, dict):
            raise ConfigError("Configuration file is empty or invalid")

        self._validate(raw)
        self._config = raw
        env_path = load_env_file()
        logger.info("Configuration Loaded Successfully")
        logger.info("Configuration loaded from %s", self.config_path)
        if env_path and env_path.exists():
            logger.info("Credentials loaded from %s", env_path)
        return self._config

    def reload(self) -> dict[str, Any]:
        global _ENV_LOADED
        _ENV_LOADED = False
        load_dotenv(DEFAULT_ENV_PATH, override=True)
        _ENV_LOADED = True
        logger.info("Reloading configuration from %s", self.config_path)
        return self.load()

    def get_broker_credentials(self) -> tuple[str, str]:
        """Return Dhan credentials from .env / environment only."""
        load_env_file()
        client_id = (os.environ.get("DHAN_CLIENT_ID") or "").strip()
        access_token = (os.environ.get("DHAN_ACCESS_TOKEN") or "").strip()
        if not client_id or not access_token:
            raise ConfigError(
                "Broker credentials missing. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN "
                f"in {DEFAULT_ENV_PATH} (copy from .env.example)."
            )
        return str(client_id), str(access_token)

    def get_server_config(self) -> dict[str, Any]:
        return self.config.get("server", {"host": "0.0.0.0", "port": 7003})

    def get_bot_config(self) -> dict[str, Any]:
        return self.config.get("bot", {})

    def get_strategy_config(self) -> dict[str, Any]:
        strategy = self.config.get("strategy")
        if not strategy or not isinstance(strategy, dict):
            raise ConfigError("strategy section is missing from configuration")
        return strategy

    def get_supertrend_config(self) -> dict[str, Any]:
        indicator = self.config.get("indicator", {})
        return indicator.get(
            "supertrend",
            {
                "enabled": True,
                "length": 10,
                "multiplier": 3,
                "timeframe": "5m",
                "timeframe_minutes": 5,
            },
        )

    def get_dhan_timeframe(self) -> str:
        """
        Map config timeframe to Dhan API interval.

        Returns ``\"DAY\"`` or a minute string like ``\"5\"``.
        """
        st = self.get_supertrend_config()
        raw = str(st.get("timeframe") or "").strip().lower()
        if not raw and st.get("timeframe_minutes") is not None:
            raw = str(st.get("timeframe_minutes")).strip().lower()
        if raw in {"1d", "1day", "day", "daily", "d"}:
            return "DAY"
        raw = raw.replace("min", "").replace("m", "")
        try:
            minutes = int(raw)
        except ValueError as exc:
            raise ConfigError(
                f"Invalid indicator.supertrend.timeframe: {st.get('timeframe')}"
            ) from exc
        if minutes not in {1, 2, 3, 5, 10, 15, 30, 60}:
            raise ConfigError(
                "indicator.supertrend.timeframe must be 1d or one of "
                "1,2,3,5,10,15,30,60 minutes"
            )
        return str(minutes)

    def get_underlying_instrument(self) -> dict[str, Any]:
        """Resolve underlying security_id / segment for REST market data."""
        trading = self.get_trading_config()
        security = self.get_security_config()
        underlying = str(
            security.get("symbol") or trading.get("underlying") or "NIFTY"
        ).upper()
        sid = str(security.get("security_id") or "").strip()
        if not sid:
            mapped = INDEX_SECURITY_IDS.get(underlying)
            if mapped is not None:
                sid = str(mapped)
        if not sid:
            raise ConfigError(
                f"security.security_id required for underlying {underlying} "
                "(set in config.yaml for 1GB VMs)"
            )
        segment = str(security.get("exchange_segment") or "IDX_I").strip() or "IDX_I"
        instrument_name = (
            str(security.get("instrument_name") or "INDEX").strip() or "INDEX"
        )
        return {
            "symbol": underlying,
            "security_id": sid,
            "exchange_segment": segment,
            "instrument_name": instrument_name,
        }

    def get_trading_config(self) -> dict[str, Any]:
        trading = self.config.get("trading")
        if not trading or not isinstance(trading, dict):
            raise ConfigError("trading section is missing from configuration")
        return trading

    def get_option_selection(self) -> dict[str, Any]:
        return self.config.get(
            "strike_selection",
            self.config.get("option_selection", {"type": "ATM", "offset": 0}),
        )

    def get_order_config(self) -> dict[str, Any]:
        return self.config.get(
            "order",
            {"order_type": "LIMIT", "limit_buffer": 0.5, "max_retries": 3},
        )

    def get_risk_config(self) -> dict[str, Any]:
        return self.config.get("risk", {})

    def get_trail_config(self) -> dict[str, Any]:
        return self.config.get(
            "trail",
            {"enabled": True, "mode": "percent", "percent": 1.0, "points": 10},
        )

    def get_security_config(self) -> dict[str, Any]:
        return self.config.get("security", {})

    def get_logging_config(self) -> dict[str, Any]:
        return self.config.get("logging", {"level": "INFO", "console": True, "file": True})

    def get_polling_seconds(self) -> int:
        bot = self.get_bot_config()
        return int(bot.get("polling_interval_seconds", 30))

    def get_port(self) -> int:
        return int(self.get_server_config().get("port", 7003))

    def get_host(self) -> str:
        return str(self.get_server_config().get("host", "0.0.0.0"))

    def is_paper_trade(self) -> bool:
        return bool(self.get_bot_config().get("paper_trade", True))

    def summary(self) -> dict[str, Any]:
        trading = self.get_trading_config()
        strategy = self.get_strategy_config()
        risk = self.get_risk_config()
        trail = self.get_trail_config()
        bot = self.get_bot_config()
        option_sel = self.get_option_selection()
        order = self.get_order_config()
        security = self.get_security_config()
        supertrend = self.get_supertrend_config()
        try:
            underlying = self.get_underlying_instrument()
        except ConfigError:
            underlying = {
                "symbol": security.get("symbol") or trading.get("underlying"),
                "security_id": security.get("security_id") or "",
                "exchange_segment": security.get("exchange_segment") or "",
            }
        return {
            "server": self.get_server_config(),
            "bot": {
                "enabled": bot.get("enabled", True),
                "polling_interval_seconds": self.get_polling_seconds(),
                "always_refresh_cli": bot.get("always_refresh_cli", True),
                "show_last_polls": bot.get("show_last_polls", 3),
                "paper_trade": self.is_paper_trade(),
            },
            "strategy": strategy,
            "supertrend": {
                **supertrend,
                "dhan_timeframe": self.get_dhan_timeframe(),
            },
            "trading": {
                "exchange": trading.get("exchange"),
                "segment": trading.get("segment", "OPTION"),
                "underlying": trading.get("underlying"),
                "expiry": trading.get("expiry"),
                "quantity": trading.get("quantity"),
                "product_type": trading.get("product_type"),
            },
            "strike_selection": option_sel,
            "order": order,
            "risk": risk,
            "trail": trail,
            "security": underlying,
        }

    def _validate(self, raw: dict[str, Any]) -> None:
        trading = raw.get("trading")
        if not trading or not isinstance(trading, dict):
            raise ConfigError("trading section is required")

        required = ["exchange", "underlying", "quantity"]
        missing = [f for f in required if trading.get(f) in (None, "")]
        if missing:
            raise ConfigError(f"Missing required trading fields: {', '.join(missing)}")

        quantity = trading.get("quantity")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ConfigError("trading.quantity must be a positive integer")

        strategy = raw.get("strategy")
        if not strategy or not isinstance(strategy, dict):
            raise ConfigError("strategy section is required")

        for key in ("entry_time", "square_off_time"):
            try:
                parse_hhmm(str(strategy.get(key, "")))
            except (TypeError, ValueError, IndexError) as exc:
                raise ConfigError(f"Invalid strategy.{key}") from exc

        st = (raw.get("indicator") or {}).get("supertrend", {})
        if st:
            length = int(st.get("length", 10))
            multiplier = float(st.get("multiplier", 3))
            if length <= 0:
                raise ConfigError("indicator.supertrend.length must be > 0")
            if multiplier <= 0:
                raise ConfigError("indicator.supertrend.multiplier must be > 0")
            # Validate timeframe via temporary config
            tf_raw = str(st.get("timeframe") or st.get("timeframe_minutes") or "5").lower()
            if tf_raw not in {"1d", "1day", "day", "daily", "d"}:
                cleaned = (
                    tf_raw.replace("min", "").replace("m", "").strip()
                )
                try:
                    minutes = int(cleaned)
                except ValueError as exc:
                    raise ConfigError(
                        "indicator.supertrend.timeframe must be 1d or minute interval"
                    ) from exc
                if minutes not in {1, 2, 3, 5, 10, 15, 30, 60}:
                    raise ConfigError(
                        "indicator.supertrend.timeframe must be 1d or one of "
                        "1,2,3,5,10,15,30,60"
                    )

        bot = raw.get("bot", {})
        polling = int(bot.get("polling_interval_seconds", 30))
        if polling < 10:
            raise ConfigError("bot.polling_interval_seconds must be at least 10")

        order = raw.get("order", {})
        order_type = str(order.get("order_type", "LIMIT")).upper()
        if order_type not in {"LIMIT", "MARKET"}:
            raise ConfigError("order.order_type must be LIMIT or MARKET")

        option_sel = raw.get("strike_selection") or raw.get("option_selection") or {}
        sel_type = str(option_sel.get("type", "ATM")).upper()
        if sel_type not in {"ATM", "ITM", "OTM"}:
            raise ConfigError("strike_selection.type must be ATM, ITM, or OTM")

        offset = int(option_sel.get("offset", option_sel.get("strike_offset", 0)))
        if offset < 0:
            raise ConfigError("strike_selection.offset must be >= 0")

        trail = raw.get("trail", {})
        if trail:
            mode = str(trail.get("mode", "percent")).lower()
            if mode not in {"percent", "points"}:
                raise ConfigError("trail.mode must be percent or points")


_config_loader: ConfigLoader | None = None


def get_config_loader(config_path: Path | str | None = None) -> ConfigLoader:
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)
    return _config_loader
