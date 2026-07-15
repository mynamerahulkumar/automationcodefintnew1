"""Lazy singleton wrapper around Dhan_SRP.Dhansrp (memory-trimmed for 1GB VMs)."""

from __future__ import annotations

import csv
import gc
import sys
import threading
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

EQUITY_CACHE_PATH = PROJECT_ROOT / "security_id" / "equity-instrument-cache.csv"

logger = get_logger()

_dhan_client: Dhansrp | None = None
_dhan_credentials_key: tuple[str, str] | None = None
_dhan_lock = threading.Lock()


def _ensure_equity_instrument_cache() -> Path:
    """
    Build a compact equity-only CSV for Dhan_SRP to load.

    Streaming filter (stdlib csv) avoids loading the full master in pandas twice.
    On a 1 GB VM the full master often causes OOM.
    """
    master = get_security_master_path()
    if EQUITY_CACHE_PATH.exists() and EQUITY_CACHE_PATH.stat().st_size > 0:
        # Rebuild if master is newer than cache
        if EQUITY_CACHE_PATH.stat().st_mtime >= master.stat().st_mtime:
            return EQUITY_CACHE_PATH

    if not master.exists():
        return master

    logger.info("Building low-memory equity instrument cache: %s", EQUITY_CACHE_PATH.name)
    EQUITY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows_written = 0
    with open(master, encoding="utf-8", newline="") as src, open(
        EQUITY_CACHE_PATH, "w", encoding="utf-8", newline=""
    ) as dst:
        reader = csv.DictReader(src)
        if not reader.fieldnames:
            return master
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            name = row.get("SEM_INSTRUMENT_NAME", "")
            if name in {"EQUITY", "INDEX"}:
                writer.writerow(row)
                rows_written += 1
    logger.info("Equity instrument cache ready (%s rows)", rows_written)
    return EQUITY_CACHE_PATH


def _trim_instrument_df(dhan: Dhansrp) -> None:
    """Drop residual non-equity rows and run GC."""
    try:
        df = getattr(dhan, "instrument_df", None)
        if df is None or getattr(df, "empty", True):
            return
        before = len(df)
        if "SEM_INSTRUMENT_NAME" not in df.columns:
            return
        keep = df["SEM_INSTRUMENT_NAME"].isin({"EQUITY", "INDEX", "ES"})
        trimmed = df.loc[keep].copy()
        dhan.instrument_df = trimmed
        del df
        gc.collect()
        logger.info(
            "Trimmed instrument master: %s -> %s rows",
            before,
            len(trimmed),
        )
    except Exception as exc:
        logger.warning("Could not trim instrument master: %s", exc)


def get_dhan_client(config_loader: ConfigLoader | None = None) -> Dhansrp:
    """Return a shared Dhansrp instance; heavy import happens only on first use."""
    global _dhan_client, _dhan_credentials_key

    loader = config_loader or get_config_loader()
    client_id, access_token = loader.get_broker_credentials()
    cred_key = (client_id, access_token)

    with _dhan_lock:
        if _dhan_client is not None and _dhan_credentials_key == cred_key:
            return _dhan_client

        from Dhan_SRP import Dhansrp  # noqa: WPS433 — lazy import saves memory at startup

        cache_path = _ensure_equity_instrument_cache()
        logger.info("Initializing Dhan client (instrument cache=%s)", cache_path.name)
        _dhan_client = Dhansrp(
            ClientCode=client_id,
            token_id=access_token,
            enable_file_logging=False,
            instrument_cache_path=str(cache_path),
            persist_instrument_file=False,
        )
        _trim_instrument_df(_dhan_client)
        _dhan_credentials_key = cred_key
        return _dhan_client


def reset_dhan_client() -> None:
    """Reset the cached Dhan client (e.g. after credential reload)."""
    global _dhan_client, _dhan_credentials_key
    with _dhan_lock:
        _dhan_client = None
        _dhan_credentials_key = None
    gc.collect()
