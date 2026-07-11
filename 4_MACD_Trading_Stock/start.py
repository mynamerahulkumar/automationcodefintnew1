#!/usr/bin/env python3
"""Start the SRP Dhan MACD/RSI Trading Bot on port 7004."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from colorama import Fore, Style, init as colorama_init

PROJECT_ROOT = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "logs"
PID_FILE = LOG_DIR / "bot.pid"
LOG_FILE = LOG_DIR / "trading.log"
UVICORN_OUT = LOG_DIR / "uvicorn.out"
HOST = "0.0.0.0"
PORT = 7004
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
SERVER_READY_TIMEOUT = 30
POLL_LOG_MARKER = "POLL SUMMARY |"
LOG_TAIL_INTERVAL = 0.3

colorama_init(autoreset=True)


def stop_existing_bot() -> None:
    """Stop a previously running bot session if one exists."""
    from core.process_manager import is_running, read_pid, stop_bot

    pid = read_pid(PID_FILE)
    if pid is None or not is_running(pid):
        return

    print("Existing bot instance detected.")
    print()
    print("Stopping previous instance...")
    print()
    if stop_bot(PID_FILE):
        print("Previous instance stopped successfully.")
        print()
    print("Starting new instance...")
    print()


def print_startup_banner(loader) -> None:
    """Resolve security_id and print startup summary."""
    from core.config_loader import ConfigError, build_equity_index

    build_equity_index()

    market = loader.get_market_config()
    strategy = loader.get_strategy_config()
    macd = loader.get_macd_config()
    rsi = loader.get_rsi_config()
    trade = loader.get_trade_config()
    risk = loader.get_risk_config()
    logging_cfg = loader.get_logging_config()
    polling = loader.get_polling_seconds()

    try:
        instrument = loader.get_resolved_instrument()
    except (ValueError, FileNotFoundError) as exc:
        raise ConfigError(f"Security lookup failed: {exc}") from exc

    print("=" * 60)
    print("                 SRP DHAN TRADING BOT")
    print("=" * 60)
    print()
    print(f"Broker              : DHAN")
    print(f"Strategy            : MACD + RSI")
    print(f"Exchange            : {market.get('exchange')}")
    print(f"Instrument          : {market.get('instrument')}")
    print(f"Trading Symbol      : {market.get('trading_symbol')}")
    print(f"Security ID         : {instrument['security_id']}")
    print(f"Timeframe           : {strategy.get('timeframe')}")
    print(f"Polling Interval    : {polling} Seconds")
    print(f"MACD Fast EMA       : {macd.get('fast')}")
    print(f"MACD Slow EMA       : {macd.get('slow')}")
    print(f"MACD Signal EMA     : {macd.get('signal')}")
    print(f"RSI Period          : {rsi.get('period')}")
    print(f"RSI Buy Level       : {rsi.get('buy')}")
    print(f"RSI Sell Level      : {rsi.get('sell')}")
    print(f"Quantity            : {trade.get('quantity')}")
    print(f"Order Type          : {trade.get('order_type')}")
    print(f"Product Type        : {trade.get('product_type')}")
    print(f"Limit Buffer        : {trade.get('limit_buffer')}")
    print(f"Take Profit         : {risk.get('take_profit_percent')}%")
    print(f"Stop Loss           : {risk.get('stop_loss_percent')}%")
    print(f"Logging             : {logging_cfg.get('level', 'INFO')}")
    print("=" * 60)
    print()
    print("Configuration Loaded Successfully.")
    print()
    print("Trading Engine Started Successfully.")
    print()
    print(f"Polling Market Every {polling} Seconds...")


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


def _signal_color(signal: str) -> str:
    signal = signal.upper()
    if signal == "BUY":
        return Fore.GREEN
    if signal == "SELL":
        return Fore.RED
    if signal == "EXIT":
        return Fore.MAGENTA
    return Fore.YELLOW


def _parse_poll_summary(line: str) -> dict[str, str] | None:
    """Parse key fields from a POLL SUMMARY log line."""
    if POLL_LOG_MARKER not in line:
        return None

    payload = line.split(POLL_LOG_MARKER, 1)[-1].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 10:
        return None

    def _value(part: str) -> str:
        return part.split(":", 1)[-1].strip() if ":" in part else part

    return {
        "symbol": parts[0],
        "price": _value(parts[1]),
        "macd": _value(parts[2]),
        "signal_line": _value(parts[3]),
        "histogram": _value(parts[4]),
        "rsi": _value(parts[5]),
        "signal": _value(parts[6]),
        "trade": _value(parts[7]),
        "position": _value(parts[8]),
        "pnl": _value(parts[9]),
    }


def _print_startup_poll_block(poll_number: int, parsed: dict[str, str]) -> None:
    """Print a formatted poll summary block for startup streaming."""
    signal = parsed["signal"]
    color = _signal_color(signal)
    print()
    print("=" * 74)
    print()
    print(f"POLL #{poll_number}")
    print()
    print(f"Price           : {parsed['price']}")
    print(f"MACD            : {parsed['macd']}")
    print(f"Signal          : {parsed['signal_line']}")
    print(f"Histogram       : {parsed['histogram']}")
    print(f"RSI             : {parsed['rsi']}")
    print(f"Signal          : {color}{signal}{Style.RESET_ALL}")
    print(f"Trade           : {parsed['trade']}")
    print(f"Position        : {parsed['position']}")
    print(f"PnL             : {parsed['pnl']}")
    print()
    print("=" * 74)


def stream_startup_poll_logs(poll_count: int, timeout_seconds: float) -> None:
    """Stream poll summaries to the CLI until poll_count polls are logged."""
    if poll_count <= 0:
        return

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.touch()

    deadline = time.time() + timeout_seconds
    polls_seen = 0

    print()
    print(f"Live poll updates (showing {poll_count} poll(s))...")

    with open(LOG_FILE, encoding="utf-8") as handle:
        handle.seek(0, 2)
        while polls_seen < poll_count and time.time() < deadline:
            line = handle.readline()
            if line:
                if POLL_LOG_MARKER in line:
                    polls_seen += 1
                    parsed = _parse_poll_summary(line)
                    if parsed:
                        _print_startup_poll_block(polls_seen, parsed)
                    else:
                        print(line, end="")
            else:
                time.sleep(LOG_TAIL_INTERVAL)

    if polls_seen < poll_count:
        print(
            f"Note: Only {polls_seen}/{poll_count} poll(s) logged within "
            f"{int(timeout_seconds)}s — bot is still running."
        )
    print()
    print("CLI log stream ended — bot continues running in background.")
    print(f"Tail logs:  python logs.py")
    print(f"Stop bot:   python stop.py")
    print(f"Log file:   {LOG_FILE}")


def main() -> None:
    from core.config_loader import get_config_loader

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(PROJECT_ROOT))

    stop_existing_bot()

    loader = get_config_loader()
    try:
        loader.load()
        print_startup_banner(loader)
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)

    max_visible_polls = loader.get_max_visible_polls()
    polling_seconds = loader.get_polling_seconds()

    env = os.environ.copy()
    if sys.stdout.isatty():
        env["LOG_CONSOLE"] = "1"

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.server:app",
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
    print(f"Server running on {HOST}:{PORT} (PID {process.pid})")

    if not wait_for_server():
        print("Warning: Server did not respond in time.")
    else:
        print(f"Health check OK: {HEALTH_URL}")
        timeout = max(
            polling_seconds * max_visible_polls + 120,
            polling_seconds * 2 + 60,
        )
        stream_startup_poll_logs(max_visible_polls, timeout)


if __name__ == "__main__":
    main()
