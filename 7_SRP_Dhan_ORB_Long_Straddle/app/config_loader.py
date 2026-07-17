"""Load and validate YAML configuration for Long Straddle ORB."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from app.logger import get_logger
from app.utils import parse_hhmm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

logger = get_logger()

_ENV_LOADED = False


def load_env_file(env_path: Path | str | None = None) -> Path | None:
    """Load credentials from project-root .env into os.environ (once)."""
    global _ENV_LOADED
    path = Path(env_path) if env_path else DEFAULT_ENV_PATH
    if path.exists():
        load_dotenv(path, override=False)
        _ENV_LOADED = True
        return path
    if not _ENV_LOADED:
        load_dotenv(override=False)
        _ENV_LOADED = True
    return path if path.exists() else None


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


class ConfigLoader:
    """Loads, validates, and exposes application configuration."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict[str, Any] = {}
        load_env_file()

    @property
    def config(self) -> dict[str, Any]:
        if not self._config:
            self.load()
        return self._config

    def load(self) -> dict[str, Any]:
        load_env_file()
        if not self.config_path.exists():
            raise ConfigError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)

        if not raw or not isinstance(raw, dict):
            raise ConfigError("Configuration file is empty or invalid")

        self._validate(raw)
        self._config = raw
        logger.info("Configuration loaded from %s", self.config_path)
        return self._config

    def reload(self) -> dict[str, Any]:
        logger.info("Reloading configuration from %s", self.config_path)
        return self.load()

    def get_broker_credentials(self) -> tuple[str, str]:
        load_env_file()
        client_id = os.environ.get("DHAN_CLIENT_ID", "").strip()
        access_token = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
        if not client_id or not access_token:
            raise ConfigError(
                "Broker credentials missing. Set DHAN_CLIENT_ID and "
                "DHAN_ACCESS_TOKEN in .env"
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

    def get_trading_config(self) -> dict[str, Any]:
        trading = self.config.get("trading")
        if not trading or not isinstance(trading, dict):
            raise ConfigError("trading section is missing from configuration")
        return trading

    def get_option_selection(self) -> dict[str, Any]:
        return self.config.get("option_selection", {"type": "ATM", "strike_offset": 0})

    def get_order_config(self) -> dict[str, Any]:
        return self.config.get("order", {"order_type": "LIMIT", "limit_buffer": 0.5})

    def get_risk_config(self) -> dict[str, Any]:
        return self.config.get("risk", {})

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
        return bool(self.get_bot_config().get("paper_trade", False))

    def get_underlying_security_id(self) -> str:
        """Return configured underlying index security_id (e.g. NIFTY=13)."""
        security = self.get_security_config()
        sid = str(security.get("security_id") or "").strip()
        return sid

    def summary(self) -> dict[str, Any]:
        trading = self.get_trading_config()
        strategy = self.get_strategy_config()
        risk = self.get_risk_config()
        bot = self.get_bot_config()
        option_sel = self.get_option_selection()
        order = self.get_order_config()
        security = self.get_security_config()
        return {
            "server": self.get_server_config(),
            "bot": {
                "enabled": bot.get("enabled", True),
                "polling_interval_seconds": self.get_polling_seconds(),
                "always_refresh_cli": bot.get("always_refresh_cli", True),
                "cli_refresh_every": bot.get("cli_refresh_every", 3),
                "paper_trade": self.is_paper_trade(),
            },
            "strategy": strategy,
            "trading": {
                "exchange": trading.get("exchange"),
                "underlying": trading.get("underlying"),
                "expiry": trading.get("expiry"),
                "quantity": trading.get("quantity"),
                "product_type": trading.get("product_type"),
            },
            "option_selection": option_sel,
            "order": order,
            "risk": risk,
            "security": {
                "symbol": security.get("symbol") or trading.get("underlying"),
                "security_id": security.get("security_id") or "",
            },
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

        opening = int(strategy.get("opening_range_minutes", 15))
        if opening <= 0:
            raise ConfigError("strategy.opening_range_minutes must be > 0")

        bot = raw.get("bot", {})
        polling = int(bot.get("polling_interval_seconds", 30))
        if polling < 10:
            raise ConfigError("bot.polling_interval_seconds must be at least 10")

        order = raw.get("order", {})
        order_type = str(order.get("order_type", "LIMIT")).upper()
        if order_type != "LIMIT":
            raise ConfigError("Only LIMIT orders are supported")

        option_sel = raw.get("option_selection", {})
        sel_type = str(option_sel.get("type", "ATM")).upper()
        if sel_type not in {"ATM", "ITM", "OTM"}:
            raise ConfigError("option_selection.type must be ATM, ITM, or OTM")

        offset = int(option_sel.get("strike_offset", 0))
        if offset < 0:
            raise ConfigError("option_selection.strike_offset must be >= 0")


_config_loader: ConfigLoader | None = None


def get_config_loader(config_path: Path | str | None = None) -> ConfigLoader:
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)
    return _config_loader
