"""Lazy Dhan clients — REST for market data (any Python), Dhan_SRP for orders."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config_loader import ConfigLoader, get_config_loader
from core.dhan_rest import DhanRestClient
from core.instrument_lookup import get_security_master_path
from core.logger import get_logger

if TYPE_CHECKING:
    from reference.Dhan_SRP import Dhansrp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = get_logger()

_dhan_client: Dhansrp | None = None
_dhan_credentials_key: tuple[str, str, bool] | None = None
_dhanhq_lite: Any | None = None
_dhanhq_lite_key: tuple[str, str] | None = None


def _should_skip_instrument_master(loader: ConfigLoader) -> bool:
    """Skip pandas CSV master when underlying security_id is configured."""
    security = loader.get_security_config()
    if security.get("skip_instrument_master"):
        return True
    return bool(str(security.get("security_id") or "").strip())


def get_dhanhq_lite(config_loader: ConfigLoader | None = None) -> DhanRestClient:
    """
    Return a lightweight REST client for candles + LTP.

    Does not import ``dhanhq`` (avoids Python <3.10 SyntaxError from match/case
    in dhanhq 2.2 ``_super_order.py``).
    """
    global _dhanhq_lite, _dhanhq_lite_key

    loader = config_loader or get_config_loader()
    client_id, access_token = loader.get_broker_credentials()
    cred_key = (client_id, access_token)

    if _dhanhq_lite is not None and _dhanhq_lite_key == cred_key:
        return _dhanhq_lite

    logger.info("Initializing Dhan REST client (market data, no dhanhq SDK)")
    _dhanhq_lite = DhanRestClient(client_id, access_token)
    _dhanhq_lite_key = cred_key
    return _dhanhq_lite


def get_dhan_client(config_loader: ConfigLoader | None = None) -> Dhansrp:
    """Return a shared Dhansrp instance; heavy import happens only on first use."""
    global _dhan_client, _dhan_credentials_key

    if sys.version_info < (3, 10):
        raise RuntimeError(
            "Order placement needs Python 3.10+ (dhanhq 2.2 uses match/case). "
            f"Current: {sys.version.split()[0]}. Upgrade Python on this host, or "
            "pip install 'dhanhq==2.0.2' for older Python. "
            "Market data polling uses REST and does not need dhanhq."
        )

    loader = config_loader or get_config_loader()
    client_id, access_token = loader.get_broker_credentials()
    skip_master = _should_skip_instrument_master(loader)
    cred_key = (client_id, access_token, skip_master)

    if _dhan_client is not None and _dhan_credentials_key == cred_key:
        return _dhan_client

    try:
        from reference.Dhan_SRP import Dhansrp  # noqa: WPS433
    except SyntaxError as exc:
        raise RuntimeError(
            "dhanhq needs Python 3.10+ (match/case). Use REST for market data "
            "or upgrade Python / pin dhanhq==2.0.2. "
            f"Import error: {exc}"
        ) from exc

    logger.info(
        "Initializing Dhan client for orders (skip_instrument_master=%s)",
        skip_master,
    )
    kwargs: dict[str, Any] = {
        "ClientCode": client_id,
        "token_id": access_token,
        "enable_file_logging": False,
        "instrument_cache_path": str(get_security_master_path()),
        "persist_instrument_file": False,
    }
    # Older Dhan_SRP copies may not accept skip_instrument_master
    try:
        _dhan_client = Dhansrp(**kwargs, skip_instrument_master=skip_master)
    except TypeError:
        _dhan_client = Dhansrp(**kwargs)
    _dhan_credentials_key = cred_key
    return _dhan_client


def reset_dhan_client() -> None:
    """Reset cached Dhan clients after credential reload."""
    global _dhan_client, _dhan_credentials_key, _dhanhq_lite, _dhanhq_lite_key
    _dhan_client = None
    _dhan_credentials_key = None
    _dhanhq_lite = None
    _dhanhq_lite_key = None
