#!/usr/bin/env python3
"""Start the FastAPI server on port 7001 (optimized for low-memory VPS)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
PID_FILE = LOG_DIR / "server.pid"
UVICORN_OUT = LOG_DIR / "uvicorn.out"
HOST = "0.0.0.0"
PORT = 7001
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
PLACE_ORDER_URL = f"http://127.0.0.1:{PORT}/place-order"
SERVER_READY_TIMEOUT = 30


def print_startup_summary() -> None:
    """Load config, resolve security_id from CSV, and print to CLI."""
    from app.config_loader import ConfigError, get_config_loader

    loader = get_config_loader()
    loader.load()
    trading = loader.get_trading_config()
    cloud = loader.get_cloud_config()

    try:
        instrument = loader.get_resolved_instrument()
    except (ValueError, FileNotFoundError) as exc:
        raise ConfigError(f"Security lookup failed: {exc}") from exc

    print("=" * 55)
    print("Dhan Limit Order API - Startup Check")
    print("=" * 55)
    print(f"Config file:    config/config.yaml")
    print(f"CSV master:     security_id/api-scrip-master.csv")
    print(f"Segment:        {trading.get('segment')}")
    print(f"Stock/Symbol:   {trading.get('stock_name')}")
    print(f"Security ID:    {instrument['security_id']}")
    print(f"Trading Symbol: {instrument['trading_symbol']}")
    print(f"Exchange:       {trading.get('exchange')} ({instrument['exchange_segment']})")
    print(f"Transaction:    {trading.get('transaction_type')}")
    print(f"Quantity:       {trading.get('quantity')}")
    print(f"Limit Price:    {trading.get('limit_price')}")
    print(f"Dry Run:        {cloud.get('dry_run', False)}")
    print("=" * 55)


def stop_existing_server() -> None:
    """Stop a previously running server session if one exists."""
    from stop import stop_server

    if stop_server(PID_FILE):
        print("Previous server session stopped.")


def wait_for_server() -> bool:
    """Wait until the API health endpoint responds."""
    for _ in range(SERVER_READY_TIMEOUT * 2):
        try:
            response = requests.get(HEALTH_URL, timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def print_order_result(data: dict, status_code: int) -> None:
    """Print a clear order placement result in the CLI."""
    print("=" * 55)
    print("ORDER PLACEMENT RESULT")
    print("=" * 55)

    status = data.get("status", "error")
    if status == "success":
        print("Result:       ORDER PLACED SUCCESSFULLY")
        print(f"Order ID:     {data.get('order_id', 'N/A')}")
        print(f"Security ID:  {data.get('security_id', 'N/A')}")
        print(f"Symbol:       {data.get('symbol', 'N/A')}")
    elif status == "dry_run":
        print("Result:       DRY RUN ONLY (order NOT sent to Dhan)")
        print(f"Security ID:  {data.get('security_id', 'N/A')}")
        print(f"Symbol:       {data.get('symbol', 'N/A')}")
        preview = data.get("preview")
        if preview:
            print(f"Preview:      {preview}")
    else:
        print("Result:       ORDER NOT PLACED")
        print(f"HTTP Status:  {status_code}")
        print(f"Message:      {data.get('message', data)}")
        message = str(data.get("message", "")).lower()
        if "invalid ip" in message or "dh-905" in message:
            print("Note:         Dhan requires your server IP to be whitelisted in Dhan settings.")
        elif "market" in message:
            print("Note:         Market may be closed (NSE: Mon-Fri 9:15 AM - 3:30 PM IST).")
        elif status_code in {502, 503, 504}:
            print("Note:         Dhan API unavailable or network issue.")

    print("=" * 55)


def place_order_on_startup() -> None:
    """Call /place-order after server is ready and print the result."""
    from app.config_loader import get_config_loader

    cloud = get_config_loader().get_cloud_config()
    if not cloud.get("auto_place_order", True):
        print("auto_place_order is false — skipping order placement.")
        return

    print("Placing order from config...")
    if not wait_for_server():
        print_order_result(
            {"status": "error", "message": "Server did not become ready in time"},
            503,
        )
        return

    try:
        response = requests.post(PLACE_ORDER_URL, timeout=60)
        try:
            data = response.json()
        except ValueError:
            data = {"status": "error", "message": response.text}
        print_order_result(data, response.status_code)
    except requests.RequestException as exc:
        print_order_result({"status": "error", "message": str(exc)}, 503)


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stop_existing_server()

    try:
        print_startup_summary()
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)

    env = os.environ.copy()
    if sys.stdout.isatty():
        env["LOG_CONSOLE"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.api:app",
        "--host",
        HOST,
        "--port",
        str(PORT),
        "--workers",
        "1",
        "--limit-concurrency",
        "10",
        "--timeout-keep-alive",
        "5",
        "--no-access-log",
    ]

    with open(UVICORN_OUT, "a", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )

    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    print(f"Started FastAPI server on {HOST}:{PORT} (PID {process.pid})")
    place_order_on_startup()
    print(f"Tail logs:      python logs.py")
    print(f"Log file:       {LOG_DIR / 'trading.log'}")


if __name__ == "__main__":
    main()
