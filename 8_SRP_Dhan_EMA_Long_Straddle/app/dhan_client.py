"""Lazy singleton wrapper around Dhan_SRP.Dhansrp."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.config_loader import ConfigLoader, get_config_loader
from app.logger import get_logger
from app.security_master import get_security_master_path

if TYPE_CHECKING:
    from Dhan_SRP import Dhansrp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = get_logger()

_dhan_client: Dhansrp | None = None
_dhan_credentials_key: tuple[str, str] | None = None


def get_dhan_client(config_loader: ConfigLoader | None = None) -> Dhansrp:
    """Return a shared Dhansrp instance; heavy import happens only on first use."""
    global _dhan_client, _dhan_credentials_key

    loader = config_loader or get_config_loader()
    client_id, access_token = loader.get_broker_credentials()
    cred_key = (client_id, access_token)

    if _dhan_client is not None and _dhan_credentials_key == cred_key:
        return _dhan_client

    from Dhan_SRP import Dhansrp  # lazy import

    logger.info("Initializing Dhan client")
    _dhan_client = Dhansrp(
        ClientCode=client_id,
        token_id=access_token,
        enable_file_logging=False,
        instrument_cache_path=str(get_security_master_path()),
        persist_instrument_file=False,
    )
    _dhan_credentials_key = cred_key
    return _dhan_client


def reset_dhan_client() -> None:
    """Reset the cached Dhan client."""
    global _dhan_client, _dhan_credentials_key
    _dhan_client = None
    _dhan_credentials_key = None
