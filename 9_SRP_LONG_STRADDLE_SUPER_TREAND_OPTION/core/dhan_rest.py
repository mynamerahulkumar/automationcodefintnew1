"""Lightweight Dhan REST client — no dhanhq SDK import (Python 3.8+ safe)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from core.logger import get_logger

logger = get_logger()

API_BASE_URL = "https://api.dhan.co/v2"
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_TIMEOUT = 60


def convert_epoch_to_ist(epoch: Any) -> datetime | Any:
    """Convert Dhan EPOCH seconds to IST datetime/date (SDK-compatible)."""
    try:
        value = int(epoch)
    except (TypeError, ValueError):
        return epoch
    dt = datetime.fromtimestamp(value, IST)
    if dt.time() == datetime.min.time():
        return dt.date()
    return dt


class DhanRestClient:
    """
    Minimal Dhan v2 HTTP client for candles + LTP.

    Avoids importing ``dhanhq`` (2.2+ uses match/case and needs Python 3.10+).
    """

    def __init__(self, client_id: str, access_token: str) -> None:
        self.client_id = str(client_id)
        self.access_token = str(access_token)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "access-token": self.access_token,
                "client-id": self.client_id,
                "Content-type": "application/json",
                "Accept": "application/json",
            }
        )

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body["dhanClientId"] = self.client_id
        url = f"{API_BASE_URL}{endpoint}"
        try:
            response = self.session.post(url, json=body, timeout=DEFAULT_TIMEOUT)
        except requests.RequestException as exc:
            logger.error("Dhan REST request failed %s: %s", endpoint, exc)
            return {"status": "failure", "remarks": str(exc), "data": ""}

        try:
            data = response.json()
        except ValueError:
            return {
                "status": "failure",
                "remarks": f"Non-JSON response HTTP {response.status_code}",
                "data": "",
            }

        if 200 <= response.status_code <= 299:
            if isinstance(data, dict) and "status" in data and "data" in data:
                return data
            return {"status": "success", "remarks": "", "data": data}

        remarks = {
            "error_code": data.get("errorCode") if isinstance(data, dict) else None,
            "error_type": data.get("errorType") if isinstance(data, dict) else None,
            "error_message": (
                data.get("errorMessage") if isinstance(data, dict) else str(data)
            ),
        }
        return {"status": "failure", "remarks": remarks, "data": ""}

    def historical_daily_data(
        self,
        security_id: str,
        exchange_segment: str,
        instrument_type: str,
        from_date: str,
        to_date: str,
        expiry_code: int = 0,
        oi: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            "/charts/historical",
            {
                "securityId": str(security_id),
                "exchangeSegment": exchange_segment,
                "instrument": instrument_type,
                "expiryCode": int(expiry_code),
                "oi": bool(oi),
                "fromDate": from_date,
                "toDate": to_date,
            },
        )

    def intraday_minute_data(
        self,
        security_id: str,
        exchange_segment: str,
        instrument_type: str,
        from_date: str,
        to_date: str,
        interval: int = 1,
        oi: bool = False,
    ) -> dict[str, Any]:
        return self._post(
            "/charts/intraday",
            {
                "securityId": str(security_id),
                "exchangeSegment": exchange_segment,
                "instrument": instrument_type,
                "interval": int(interval),
                "oi": bool(oi),
                "fromDate": from_date,
                "toDate": to_date,
            },
        )

    def ticker_data(self, securities: dict[str, list[int]]) -> dict[str, Any]:
        return self._post("/marketfeed/ltp", dict(securities))

    def convert_to_date_time(self, epoch: Any) -> Any:
        return convert_epoch_to_ist(epoch)
