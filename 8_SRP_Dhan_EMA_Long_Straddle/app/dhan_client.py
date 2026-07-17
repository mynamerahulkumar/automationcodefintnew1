"""Lazy Dhan clients — REST for market data (any Python), Dhan_SRP for orders."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config_loader import ConfigLoader, get_config_loader
from app.dhan_rest import DhanRestClient
from app.logger import get_logger
from app.security_master import get_security_master_path

if TYPE_CHECKING:
    from Dhan_SRP import Dhansrp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = get_logger()

_dhan_client: Dhansrp | None = None
_dhan_credentials_key: tuple[str, str, bool] | None = None
_dhanhq_lite: Any | None = None
_dhanhq_lite_key: tuple[str, str] | None = None


def _should_skip_instrument_master(loader: ConfigLoader) -> bool:
    """
    Skip CSV load only when explicitly requested for a known underlying id
    and option selection is not needed from CSV this session.

    For Long Straddle, option CE/PE resolution needs the master at entry,
    so default is False. Poll path never calls get_dhan_client().
    """
    security = loader.get_security_config()
    # Prefer loading master for F&O option lookup unless user forces skip.
    return bool(security.get("skip_instrument_master", False))


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
            "pip install 'dhanhq==2.0.2' for older Python."
        )

    loader = config_loader or get_config_loader()
    client_id, access_token = loader.get_broker_credentials()
    skip_master = _should_skip_instrument_master(loader)
    cred_key = (client_id, access_token, skip_master)

    if _dhan_client is not None and _dhan_credentials_key == cred_key:
        return _dhan_client

    try:
        from Dhan_SRP import Dhansrp  # noqa: WPS433
    except SyntaxError as exc:
        raise RuntimeError(
            "Failed to import dhanhq/Dhan_SRP due to Python syntax mismatch "
            f"({exc}). Use Python 3.10+ or pip install 'dhanhq==2.0.2'."
        ) from exc

    logger.info(
        "Initializing Dhan client (skip_instrument_master=%s)",
        skip_master,
    )
    _dhan_client = Dhansrp(
        ClientCode=client_id,
        token_id=access_token,
        enable_file_logging=False,
        instrument_cache_path=str(get_security_master_path()),
        persist_instrument_file=False,
        skip_instrument_master=skip_master,
    )
    _dhan_credentials_key = cred_key
    return _dhan_client


def reset_dhan_client() -> None:
    """Reset cached Dhan clients after credential reload."""
    global _dhan_client, _dhan_credentials_key, _dhanhq_lite, _dhanhq_lite_key
    _dhan_client = None
    _dhan_credentials_key = None
    _dhanhq_lite = None
    _dhanhq_lite_key = None
