#!/usr/bin/env python3
"""Start the SRP EMA Crossover Trading Engine on port 7001."""

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
LOG_FILE = LOG_DIR / "trading.log"
UVICORN_OUT = LOG_DIR / "uvicorn.out"
HOST = "0.0.0.0"
PORT = 7001
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
STATUS_URL = f"http://127.0.0.1:{PORT}/status"
SERVER_READY_TIMEOUT = 45
STATUS_POLL_INTERVAL = 1.0


def print_startup_banner() -> None:
    """Load config, resolve security_id, and print startup summary."""
    from app.config_loader import ConfigError, get_config_loader
    from app.security_master import build_equity_index

    loader = get_config_loader()
    loader.load()
    build_equity_index()

    trading = loader.get_trading_config()
    strategy = loader.get_strategy_config()
    risk = loader.get_risk_config()
    bot = loader.get_bot_config()

    try:
        instrument = loader.get_resolved_instrument()
    except (ValueError, FileNotFoundError) as exc:
        raise ConfigError(f"Security lookup failed: {exc}") from exc

    mode = "PAPER" if bot.get("paper_trade") else "LIVE"

    print("=" * 34)
    print("SRP Trading Engine")
    print("=" * 34)
    print()
    print(f"Mode              {mode}")
    print()
    print("Broker            DHAN")
    print()
    print("Strategy          EMA Crossover")
    print()
    print(f"Exchange          {trading.get('exchange')}")
    print()
    print(f"Segment           {trading.get('segment')}")
    print()
    print(f"Stock             {trading.get('stock_name')}")
    print()
    print(f"Security ID       {instrument['security_id']}")
    print()
    print(f"Fast EMA          {strategy.get('fast_ema')}")
    print()
    print(f"Slow EMA          {strategy.get('slow_ema')}")
    print()
    print(f"Timeframe         {strategy.get('timeframe')}")
    print()
    print(f"Polling           {strategy.get('polling_seconds')} sec")
    print()
    print(f"TP                {risk.get('target_percent')}%")
    print()
    print(f"SL                {risk.get('stoploss_percent')}%")
    print()
    print("Status            RUNNING")
    print("=" * 34)
    sys.stdout.flush()


def stop_existing_bot() -> None:
    """Stop a previously running bot session if one exists."""
    from stop import stop_bot

    if stop_bot(PID_FILE):
        print("Previous bot session stopped.")
        time.sleep(1)


def wait_for_server(timeout: int = SERVER_READY_TIMEOUT) -> bool:
    """Wait until the API health endpoint responds."""
    for i in range(timeout * 2):
        try:
            response = requests.get(HEALTH_URL, timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        if i % 4 == 0:
            print(f"  Waiting for server... ({i // 2}s)", flush=True)
        time.sleep(0.5)
    return False


def _print_status_poll(poll_number: int, data: dict, strategy: dict, trading: dict) -> None:
    """Print one poll block from /status JSON."""
    from app.cli_display import print_poll_summary_block

    segment = str(trading.get("segment", "EQUITY"))
    print_poll_summary_block(
        poll_number=poll_number,
        symbol=str(data.get("symbol") or trading.get("stock_name") or ""),
        segment=segment,
        fast_period=int(strategy.get("fast_ema", 9)),
        slow_period=int(strategy.get("slow_ema", 21)),
        current_price=data.get("current_price"),
        fast_ema=data.get("fast_ema"),
        slow_ema=data.get("slow_ema"),
        signal=data.get("current_signal"),
        candle_time=data.get("last_candle_time"),
        last_error=data.get("last_error"),
    )


def stream_startup_poll_logs(poll_count: int, timeout_seconds: float, process: subprocess.Popen) -> None:
    """
    Wait for poll_count completed polls via /status, print LTP + EMA to CLI,
    then return so start.py can exit while the bot keeps running.
    """
    if poll_count <= 0:
        return

    from app.config_loader import get_config_loader

    loader = get_config_loader()
    strategy = loader.get_strategy_config()
    trading = loader.get_trading_config()

    deadline = time.time() + timeout_seconds
    last_seen_count = 0
    polls_printed = 0

    print()
    print(f"Live poll updates (showing {poll_count} poll(s))...")
    print("First poll may take 15–40s (Dhan client + candle fetch).")
    print("=" * 55, flush=True)

    last_wait_msg = 0.0
    while polls_printed < poll_count and time.time() < deadline:
        if process.poll() is not None:
            print()
            print(f"ERROR: Server process exited early (exit={process.returncode}).")
            print(f"Check {UVICORN_OUT} for details.")
            print("Tip: run with the project venv:")
            print("  source venv/bin/activate && python start.py")
            return

        try:
            response = requests.get(STATUS_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                poll_count_now = int(data.get("poll_count") or 0)
                if poll_count_now > last_seen_count:
                    # Print each new poll since last check
                    for _ in range(poll_count_now - last_seen_count):
                        if polls_printed >= poll_count:
                            break
                        polls_printed += 1
                        _print_status_poll(polls_printed, data, strategy, trading)
                    last_seen_count = poll_count_now
                elif time.time() - last_wait_msg >= 10:
                    status = data.get("bot_status", "?")
                    err = data.get("last_error")
                    msg = f"  Still waiting for poll... status={status}"
                    if err:
                        msg += f" error={err}"
                    print(msg, flush=True)
                    last_wait_msg = time.time()
        except requests.RequestException as exc:
            if time.time() - last_wait_msg >= 10:
                print(f"  Waiting for status API... ({exc.__class__.__name__})", flush=True)
                last_wait_msg = time.time()

        time.sleep(STATUS_POLL_INTERVAL)

    print("=" * 55)
    if polls_printed < poll_count:
        print(
            f"Note: Only {polls_printed}/{poll_count} poll(s) within "
            f"{int(timeout_seconds)}s — bot may still be running."
        )
        print(f"Check status:   curl {STATUS_URL}")
        print(f"Check logs:     python logs.py")
        print(f"Uvicorn out:    {UVICORN_OUT}")
    print("CLI log stream ended — bot continues running in background.")
    print("Tail logs:      python logs.py")
    print("Stop bot:       python stop.py")
    print(f"Log file:       {LOG_FILE}")
    sys.stdout.flush()


def main() -> None:
    from app.config_loader import get_config_loader, load_env_file

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    stop_existing_bot()

    # Load .env into this process so the uvicorn child inherits credentials
    load_env_file()

    loader = get_config_loader()
    try:
        loader.load()
        loader.get_broker_credentials()
        print_startup_banner()
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)

    bot_cfg = loader.get_bot_config()
    startup_poll_logs = int(bot_cfg.get("startup_poll_logs", 2))
    polling_seconds = loader.get_polling_seconds()

    env = os.environ.copy()
    # Avoid console handlers on uvicorn stdout (they go to uvicorn.out, not this CLI)
    env.pop("LOG_CONSOLE", None)

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
    print(f"Started SRP Trading Engine on {HOST}:{PORT} (PID {process.pid})")
    print(f"Python: {sys.executable}", flush=True)

    # Quick exit detection (missing deps / import errors)
    time.sleep(1.5)
    if process.poll() is not None:
        print(f"ERROR: Server exited immediately (code={process.returncode}).")
        print(f"Last lines of {UVICORN_OUT}:")
        try:
            lines = UVICORN_OUT.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-30:]:
                print(f"  {line}")
        except OSError:
            pass
        print("Tip: use the project venv:")
        print("  source venv/bin/activate && python start.py")
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    if startup_poll_logs > 0:
        if not wait_for_server():
            print("Warning: Server did not respond in time — skipping startup poll display.")
            print(f"Check {UVICORN_OUT}")
        else:
            # First poll includes Dhan client init + ~2s sleep inside historical API
            timeout = max(
                polling_seconds * startup_poll_logs + 180,
                240,
            )
            stream_startup_poll_logs(startup_poll_logs, timeout, process)
    else:
        print("Tail logs:      python logs.py")
        print(f"Log file:       {LOG_FILE}")


if __name__ == "__main__":
    main()
