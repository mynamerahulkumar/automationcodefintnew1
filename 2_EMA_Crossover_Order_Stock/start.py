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
SERVER_READY_TIMEOUT = 30
POLL_LOG_MARKER = "POLL SUMMARY |"
LOG_TAIL_INTERVAL = 0.3


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


def stop_existing_bot() -> None:
    """Stop a previously running bot session if one exists."""
    from stop import stop_bot

    if stop_bot(PID_FILE):
        print("Previous bot session stopped.")


def wait_for_server(timeout: int = SERVER_READY_TIMEOUT) -> bool:
    """Wait until the API health endpoint responds."""
    for _ in range(timeout * 2):
        try:
            response = requests.get(HEALTH_URL, timeout=1)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def _parse_poll_summary(line: str) -> dict[str, str] | None:
    """Parse key fields from a POLL SUMMARY log line."""
    if POLL_LOG_MARKER not in line:
        return None

    payload = line.split(POLL_LOG_MARKER, 1)[-1].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 7:
        return None

    symbol_segment = parts[0]
    symbol = symbol_segment.split("(")[0].strip()
    segment = "EQUITY"
    if "(" in symbol_segment and ")" in symbol_segment:
        segment = symbol_segment.split("(", 1)[1].rsplit(")", 1)[0].strip()

    def _value(part: str) -> str:
        return part.split(":", 1)[-1].strip() if ":" in part else part

    return {
        "symbol": symbol,
        "segment": segment,
        "ltp": _value(parts[1]),
        "fast_ema": parts[2],
        "slow_ema": parts[3],
        "trend": _value(parts[4]),
        "signal": _value(parts[5]),
        "candle": _value(parts[6]),
    }


def stream_startup_poll_logs(poll_count: int, timeout_seconds: float) -> None:
    """
    Stream poll summaries to the CLI until poll_count polls are logged,
    then return so start.py can exit while the bot keeps running.
    """
    if poll_count <= 0:
        return

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.touch()

    deadline = time.time() + timeout_seconds
    polls_seen = 0

    print()
    print(f"Live poll updates (showing {poll_count} poll(s))...")
    print("=" * 55)

    with open(LOG_FILE, encoding="utf-8") as handle:
        handle.seek(0, 2)
        while polls_seen < poll_count and time.time() < deadline:
            line = handle.readline()
            if line:
                if POLL_LOG_MARKER in line:
                    polls_seen += 1
                    parsed = _parse_poll_summary(line)
                    if parsed:
                        price_label = (
                            "Option Price (LTP)"
                            if parsed["segment"].upper() == "OPTION"
                            else "Stock Price (LTP)"
                        )
                        print()
                        print(f"  Poll #{polls_seen} — {parsed['symbol']} [{parsed['segment']}]")
                        print(f"  {price_label:<22}: {parsed['ltp']}")
                        for key in ("fast_ema", "slow_ema"):
                            label, value = parsed[key].split(":", 1)
                            print(f"  {label.strip():<22}: {value.strip()}")
                        print(f"  {'Trend':<22}: {parsed['trend']}")
                        print(f"  {'Signal':<22}: {parsed['signal']}")
                        print(f"  {'Candle Time':<22}: {parsed['candle']}")
                    else:
                        print(line, end="")
            else:
                time.sleep(LOG_TAIL_INTERVAL)

    print("=" * 55)
    if polls_seen < poll_count:
        print(
            f"Note: Only {polls_seen}/{poll_count} poll(s) logged within "
            f"{int(timeout_seconds)}s — bot is still running."
        )
    print("CLI log stream ended — bot continues running in background.")
    print(f"Tail logs:      python logs.py")
    print(f"Stop bot:       python stop.py")
    print(f"Log file:       {LOG_FILE}")


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
        # Fail fast if credentials are missing before starting the server
        loader.get_broker_credentials()
        print_startup_banner()
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)

    bot_cfg = loader.get_bot_config()
    startup_poll_logs = int(bot_cfg.get("startup_poll_logs", 2))
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

    if startup_poll_logs > 0:
        if not wait_for_server():
            print("Warning: Server did not respond in time — skipping startup log stream.")
        else:
            # Buffer for Dhan API latency (historical data calls include delays)
            timeout = max(
                polling_seconds * startup_poll_logs + 120,
                polling_seconds * 2 + 60,
            )
            stream_startup_poll_logs(startup_poll_logs, timeout)
    else:
        print(f"Tail logs:      python logs.py")
        print(f"Log file:       {LOG_FILE}")


if __name__ == "__main__":
    main()
