"""Load and validate YAML configuration."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from app.logger import get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

logger = get_logger()

TIMEFRAME_PATTERN = re.compile(r"^(\d+)(m|min|minute|h|hour|d|day)?$", re.IGNORECASE)


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


class ConfigLoader:
    """Loads, validates, and hot-reloads application configuration."""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: dict[str, Any] = {}

    @property
    def config(self) -> dict[str, Any]:
        """Return the currently loaded configuration."""
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
        logger.info("Configuration loaded from %s", self.config_path)
        return self._config

    def reload(self) -> dict[str, Any]:
        """Reload configuration from disk."""
        logger.info("Reloading configuration from %s", self.config_path)
        return self.load()

    def get_broker_credentials(self) -> tuple[str, str]:
        """Return Dhan client_id and access_token with env overrides."""
        broker = self.config.get("broker", {})
        client_id = os.environ.get("DHAN_CLIENT_ID") or broker.get("client_id", "")
        access_token = os.environ.get("DHAN_ACCESS_TOKEN") or broker.get("access_token", "")

        if not client_id or not access_token:
            raise ConfigError(
                "Broker credentials missing. Set broker.client_id and broker.access_token "
                "in config or DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN env vars."
            )
        return str(client_id), str(access_token)

    def get_trading_config(self) -> dict[str, Any]:
        """Return the trading section of the configuration."""
        trading = self.config.get("trading")
        if not trading or not isinstance(trading, dict):
            raise ConfigError("trading section is missing from configuration")
        return trading

    def get_strategy_config(self) -> dict[str, Any]:
        """Return the strategy section of the configuration."""
        strategy = self.config.get("strategy")
        if not strategy or not isinstance(strategy, dict):
            raise ConfigError("strategy section is missing from configuration")
        return strategy

    def get_risk_config(self) -> dict[str, Any]:
        """Return the risk section of the configuration."""
        return self.config.get("risk", {})

    def get_bot_config(self) -> dict[str, Any]:
        """Return the bot section of the configuration."""
        return self.config.get("bot", {})

    def get_polling_seconds(self) -> int:
        """Return configured polling interval in seconds."""
        strategy = self.get_strategy_config()
        return int(strategy.get("polling_seconds", 30))

    def parse_timeframe_minutes(self) -> int:
        """Convert strategy.timeframe (e.g. 5m) to minute interval for Dhan API."""
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
            raise ConfigError("DAY timeframe not supported for EMA crossover polling")
        raise ConfigError(f"Invalid strategy.timeframe unit: {raw}")

    def summary(self) -> dict[str, Any]:
        """Return a safe summary of the loaded configuration."""
        trading = self.get_trading_config()
        strategy = self.get_strategy_config()
        risk = self.get_risk_config()
        bot = self.get_bot_config()
        return {
            "segment": trading.get("segment"),
            "exchange": trading.get("exchange"),
            "stock_name": trading.get("stock_name"),
            "security_id": trading.get("security_id"),
            "quantity": trading.get("quantity"),
            "transaction_type": trading.get("transaction_type"),
            "order_type": trading.get("order_type"),
            "limit_price": trading.get("limit_price"),
            "product_type": trading.get("product_type"),
            "strategy": strategy,
            "risk": risk,
            "bot": {
                "paper_trade": bot.get("paper_trade", False),
                "one_position_only": bot.get("one_position_only", True),
                "cooldown_seconds": bot.get("cooldown_seconds", 60),
                "log_level": bot.get("log_level", "INFO"),
                "startup_poll_logs": bot.get("startup_poll_logs", 2),
            },
        }

    def get_resolved_instrument(self) -> dict[str, Any]:
        """Resolve security_id from api-scrip-master.csv using trading config."""
        from app.security_master import resolve_instrument

        return resolve_instrument(self.get_trading_config())

    def _validate(self, raw: dict[str, Any]) -> None:
        """Validate required configuration fields."""
        trading = raw.get("trading")
        if not trading or not isinstance(trading, dict):
            raise ConfigError("trading section is required in configuration")

        required = ["segment", "exchange", "stock_name", "quantity"]
        missing = [field for field in required if trading.get(field) in (None, "")]
        if missing:
            raise ConfigError(f"Missing required trading fields: {', '.join(missing)}")

        order_type = str(trading.get("order_type", "LIMIT")).upper()
        if order_type != "LIMIT":
            raise ConfigError("Only LIMIT orders are supported")

        segment = str(trading.get("segment", "")).upper()
        if segment not in {"EQUITY", "OPTION"}:
            raise ConfigError("trading.segment must be EQUITY or OPTION")

        if segment == "OPTION":
            option_required = ["expiry", "strike", "option_type"]
            option_missing = [
                field for field in option_required if trading.get(field) in (None, "")
            ]
            if option_missing:
                raise ConfigError(
                    f"Missing required option fields: {', '.join(option_missing)}"
                )

        quantity = trading.get("quantity")
        if not isinstance(quantity, int) or quantity <= 0:
            raise ConfigError("trading.quantity must be a positive integer")

        strategy = raw.get("strategy")
        if not strategy or not isinstance(strategy, dict):
            raise ConfigError("strategy section is required in configuration")

        strategy_name = str(strategy.get("name", "")).upper()
        if strategy_name != "EMA_CROSSOVER":
            raise ConfigError("Only EMA_CROSSOVER strategy is supported currently")

        fast_ema = int(strategy.get("fast_ema", 9))
        slow_ema = int(strategy.get("slow_ema", 21))
        if fast_ema >= slow_ema:
            raise ConfigError("strategy.fast_ema must be less than strategy.slow_ema")

        polling = int(strategy.get("polling_seconds", 30))
        if polling < 10:
            raise ConfigError("strategy.polling_seconds must be at least 10")

        bot = raw.get("bot", {})
        startup_poll_logs = int(bot.get("startup_poll_logs", 2))
        if startup_poll_logs < 0:
            raise ConfigError("bot.startup_poll_logs must be 0 or greater")

        # Validate timeframe parses correctly
        loader = ConfigLoader.__new__(ConfigLoader)
        loader._config = raw
        loader.parse_timeframe_minutes()


_config_loader: ConfigLoader | None = None


def get_config_loader(config_path: Path | str | None = None) -> ConfigLoader:
    """Return the shared configuration loader instance."""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)
    return _config_loader
