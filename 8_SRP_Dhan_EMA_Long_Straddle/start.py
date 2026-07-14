#!/usr/bin/env python3
"""Start the SRP Dhan Long Straddle EMA Confirmation bot on port 7003."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
RUN_DIR = PROJECT_ROOT / "run"
PID_FILE = RUN_DIR / "bot.pid"
LOG_FILE = LOG_DIR / "bot.log"
UVICORN_OUT = LOG_DIR / "uvicorn.out"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7003
SERVER_READY_TIMEOUT = 30
POLL_LOG_MARKER = "POLL SUMMARY |"
CLI_DASHBOARD_MARKER = "CLI DASHBOARD"
LOG_TAIL_INTERVAL = 0.3


def print_startup_banner() -> None:
    from app.cli_display import build_startup_banner
    from app.config_loader import get_config_loader

    loader = get_config_loader()
    loader.load()
    print(build_startup_banner(loader.summary(), bot_status="RUNNING"))


def stop_existing_bot() -> None:
    from stop import stop_bot

    if stop_bot(PID_FILE):
        print("Previous bot session stopped.")


def wait_for_server(port: int, timeout: int = SERVER_READY_TIMEOUT) -> bool:
    health_url = f"http://127.0.0.1:{port}/health"
    for _ in range(timeout * 2):
        try:
            response = requests.get(health_url, timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def stream_cli_updates(duration_seconds: float) -> None:
    """Stream poll dashboards from the log for a short period after startup."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.touch()

    deadline = time.time() + duration_seconds
    print()
    print("Live poll updates (Ctrl+C returns; bot keeps running)...")
    print("=" * 56)

    with open(LOG_FILE, encoding="utf-8") as handle:
        handle.seek(0, 2)
        try:
            while time.time() < deadline:
                line = handle.readline()
                if not line:
                    time.sleep(LOG_TAIL_INTERVAL)
                    continue
                if CLI_DASHBOARD_MARKER in line or POLL_LOG_MARKER in line:
                    # Print remaining multi-line dashboard if present
                    print(line, end="")
                    # Drain a few following lines that belong to the dashboard
                    for _ in range(40):
                        nxt = handle.readline()
                        if not nxt:
                            break
                        print(nxt, end="")
                        if nxt.strip().startswith("-" * 10) and "POLL" not in nxt:
                            # likely closing separator already printed; keep going one more
                            pass
                        if POLL_LOG_MARKER in nxt:
                            break
        except KeyboardInterrupt:
            pass

    print("=" * 56)
    print("CLI log stream ended — bot continues running in background.")
    print("Tail logs:      python logs.py")
    print("Stop bot:       python stop.py")
    print(f"Log file:       {LOG_FILE}")


def main() -> None:
    from app.config_loader import get_config_loader

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    stop_existing_bot()

    loader = get_config_loader()
    try:
        loader.load()
        # Credentials check early so banner failure is clear
        try:
            loader.get_broker_credentials()
        except Exception as cred_exc:
            print(f"Warning: {cred_exc}")
            print("Set dhan.client_id / dhan.access_token or DHAN_* env vars before live trading.")
        print_startup_banner()
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)

    host = loader.get_host()
    port = loader.get_port()
    bot_cfg = loader.get_bot_config()
    polling_seconds = loader.get_polling_seconds()

    env = os.environ.copy()
    if sys.stdout.isatty():
        env["LOG_CONSOLE"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.api:app",
        "--host",
        host,
        "--port",
        str(port),
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
    print(f"Started SRP Long Straddle EMA bot on {host}:{port} (PID {process.pid})")

    if bool(bot_cfg.get("always_refresh_cli", True)):
        if not wait_for_server(port):
            print("Warning: Server did not respond in time — skipping startup log stream.")
        else:
            stream_cli_updates(max(polling_seconds * 3 + 30, 60))
    else:
        print("Tail logs:      python logs.py")
        print(f"Log file:       {LOG_FILE}")


if __name__ == "__main__":
    main()
