#!/usr/bin/env python3
"""Start the SRP Dhan EMA/RSI Trading Bot on port 7003."""

from __future__ import annotations

import os
import re
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
PORT = 7003
HEALTH_URL = f"http://127.0.0.1:{PORT}/health"
SERVER_READY_TIMEOUT = 30
POLL_LOG_MARKER = "POLL SUMMARY |"
LOG_TAIL_INTERVAL = 0.3
LOG_MESSAGE_PATTERN = re.compile(
    r"^(ERROR|WARNING):\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+:(.*)$"
)

colorama_init(autoreset=True)


def _strategy_label(mode: str) -> str:
    labels = {
        "EMA": "EMA",
        "RSI": "RSI",
        "EMA_RSI": "EMA + RSI",
    }
    return labels.get(mode.upper(), mode)


def print_startup_banner(loader) -> None:
    """Resolve security_id and print startup summary."""
    from core.config_loader import ConfigError

    market = loader.get_market_config()
    strategy = loader.get_strategy_config()
    ema = loader.get_ema_config()
    rsi = loader.get_rsi_config()
    trade = loader.get_trade_config()
    risk = loader.get_risk_config()
    polling = loader.get_polling_seconds()
    startup_poll_logs = loader.get_startup_poll_logs()

    try:
        instrument = loader.get_resolved_instrument()
    except (ValueError, FileNotFoundError) as exc:
        raise ConfigError(f"Security lookup failed: {exc}") from exc

    mode = str(strategy.get("mode", "EMA")).upper()

    print("=" * 50)
    print("SRP DHAN TRADING BOT")
    print("=" * 50)
    print()
    print(f"Broker           : DHAN")
    print(f"Strategy         : {_strategy_label(mode)}")
    print(f"Exchange         : {market.get('exchange')}")
    print(f"Instrument       : {market.get('instrument')}")
    print(f"Trading Symbol   : {market.get('trading_symbol')}")
    print(f"Security ID      : {instrument['security_id']}")
    print(f"Timeframe        : {strategy.get('timeframe')}")
    if mode in {"EMA", "EMA_RSI"}:
        print(f"Fast EMA         : {ema.get('fast')}")
        print(f"Slow EMA         : {ema.get('slow')}")
    if mode in {"RSI", "EMA_RSI"}:
        print(f"RSI Period       : {rsi.get('period')}")
        print(f"RSI Buy          : {rsi.get('buy')}")
        print(f"RSI Sell         : {rsi.get('sell')}")
    print(f"Quantity         : {trade.get('quantity')}")
    print(f"Order Type       : {trade.get('order_type')}")
    print(f"Take Profit      : {risk.get('take_profit_percent')}%")
    print(f"Stop Loss        : {risk.get('stop_loss_percent')}%")
    print(f"Polling          : {polling} Seconds")
    print(f"Startup Polls    : {startup_poll_logs}")
    print(f"Python           : {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print(
            "Note             : Python <3.10 — market data uses REST; "
            "upgrade to 3.10+ for live order placement (dhanhq 2.2)"
        )
    print("=" * 50)
    print()
    print("Bot Started Successfully...")


def stop_existing_bot() -> None:
    """Stop a previously running bot session if one exists."""
    from core.process_manager import stop_bot

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


def _signal_color(signal: str) -> str:
    signal = signal.upper()
    if signal == "BUY":
        return Fore.GREEN
    if signal == "SELL":
        return Fore.RED
    return Fore.YELLOW


def _parse_poll_summary(line: str) -> dict[str, str] | None:
    """Parse key fields from a POLL SUMMARY log line."""
    if POLL_LOG_MARKER not in line:
        return None

    payload = line.split(POLL_LOG_MARKER, 1)[-1].strip()
    parts = [part.strip() for part in payload.split("|")]
    if len(parts) < 9:
        return None

    def _value(part: str) -> str:
        return part.split(":", 1)[-1].strip() if ":" in part else part

    return {
        "symbol": parts[0],
        "ltp": _value(parts[1]),
        "high": _value(parts[2]),
        "low": _value(parts[3]),
        "ema_fast": parts[4],
        "ema_slow": parts[5],
        "rsi": parts[6],
        "signal": _value(parts[7]),
        "trade": _value(parts[8]),
    }


def _print_startup_poll_block(poll_number: int, parsed: dict[str, str]) -> None:
    """Print a formatted poll summary block for startup streaming."""
    signal = parsed["signal"]
    color = _signal_color(signal)
    print()
    print(f"  Poll #{poll_number} — {parsed['symbol']}")
    print(f"  {'LTP':<22}: {parsed['ltp']}")
    print(f"  {'Candle High':<22}: {parsed['high']}")
    print(f"  {'Candle Low':<22}: {parsed['low']}")
    for key in ("ema_fast", "ema_slow", "rsi"):
        label, value = parsed[key].split(":", 1)
        print(f"  {label.strip():<22}: {value.strip()}")
    print(f"  {'Signal':<22}: {color}{signal}{Style.RESET_ALL}")
    print(f"  {'Trade':<22}: {parsed['trade']}")


def _extract_poll_error(line: str) -> str | None:
    """Return a short poll-cycle error message for CLI feedback."""
    stripped = line.strip()
    lowered = stripped.lower()

    match = LOG_MESSAGE_PATTERN.match(stripped)
    if match:
        level, message = match.group(1), match.group(2).strip()
        is_error = level == "ERROR"
        is_warning = level == "WARNING"
    else:
        message = stripped
        is_error = stripped.startswith("ERROR:")
        is_warning = stripped.startswith("WARNING:")
        if not (is_error or is_warning):
            if any(
                key in stripped
                for key in (
                    "MemoryError",
                    "ModuleNotFoundError",
                    "ImportError",
                    "ConfigError",
                )
            ):
                return stripped
            return None
        # Fallback: strip LEVEL:timestamp: if present
        if ":" in message:
            message = message.split(":", 2)[-1].strip()

    lowered_msg = message.lower()

    if "dh-901" in lowered or "invalid_authentication" in lowered:
        return (
            "Dhan auth failed (DH-901) — refresh DHAN_ACCESS_TOKEN in .env"
        )
    if "dh-902" in lowered or "not subscribed to data apis" in lowered:
        return (
            "Dhan Data API not subscribed (DH-902) — enable Data APIs on "
            "web.dhan.co to fetch LTP/EMA/RSI"
        )
    if "memoryerror" in lowered_msg:
        return (
            "Out of memory — keep security_id in config.yaml; "
            "do not load api-scrip-master.csv on 1GB VMs"
        )
    if "invalid syntax" in lowered_msg and "_super_order" in lowered_msg:
        return (
            "dhanhq needs Python 3.10+ (match/case). "
            "Redeploy this build (REST market data) or upgrade Python on AWS"
        )
    if "invalid syntax" in lowered_msg:
        return (
            f"Python syntax error — {message}. "
            "Use Python 3.10+ on AWS (check: python3 --version)"
        )
    if "modulenotfounderror" in lowered_msg or "no module named" in lowered_msg:
        missing = message.rsplit(":", 1)[-1].strip().strip("'\"")
        return f"Missing dependency — {missing}"
    if "empty candle data" in lowered_msg:
        return "No candle data — check Dhan token / Data API subscription"
    if "failed to fetch candles" in lowered_msg:
        return message
    if "ltp fetch failed" in lowered_msg:
        return message
    if "exception in getting ohlc" in lowered_msg:
        return "OHLC fetch failed — check logs/trading.log for Dhan API error"
    if "unhandled error in poll cycle" in lowered_msg:
        detail = message.split("Unhandled error in poll cycle", 1)[-1].lstrip(": ").strip()
        if detail:
            return f"Poll cycle failed — {detail}"
        return "Poll cycle failed — check logs/trading.log for details."
    if is_error:
        return message
    if is_warning and (
        "insufficient candles" in lowered_msg or "empty candle" in lowered_msg
    ):
        return message
    return None


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
    last_error: str | None = None
    traceback_buffer: list[str] = []

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
                    traceback_buffer.clear()
                    parsed = _parse_poll_summary(line)
                    if parsed:
                        _print_startup_poll_block(polls_seen, parsed)
                    else:
                        print(line, end="")
                else:
                    error_text = _extract_poll_error(line)
                    if error_text and error_text != last_error:
                        last_error = error_text
                        print(f"  ERROR: {error_text}")
                    elif line.startswith("Traceback") or (
                        traceback_buffer and line.startswith(" ")
                    ):
                        traceback_buffer.append(line.rstrip())
                        if line.startswith(" ") is False and "Error" in line:
                            detail = line.strip()
                            if detail and detail != last_error:
                                last_error = detail
                                print(f"  ERROR: {detail}")
                            traceback_buffer.clear()
            else:
                time.sleep(LOG_TAIL_INTERVAL)

    print("=" * 55)
    if polls_seen == 0 and last_error:
        print(f"Startup polls failed: {last_error}")
        print("See full details in logs/trading.log and logs/uvicorn.out")
    elif polls_seen < poll_count:
        print(
            f"Note: Only {polls_seen}/{poll_count} poll(s) logged within "
            f"{int(timeout_seconds)}s — bot is still running."
        )
    print("CLI log stream ended — bot continues running in background.")
    print(f"Tail logs:  python logs.py")
    print(f"Stop bot:   python stop.py")
    print(f"Log file:   {LOG_FILE}")


def main() -> None:
    from core.config_loader import get_config_loader

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stop_existing_bot()

    sys.path.insert(0, str(PROJECT_ROOT))

    loader = get_config_loader()
    try:
        loader.load()
        print_startup_banner(loader)
    except Exception as exc:
        print(f"Startup failed: {exc}")
        sys.exit(1)

    startup_poll_logs = loader.get_startup_poll_logs()
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

    if startup_poll_logs > 0:
        if not wait_for_server():
            print("Warning: Server did not respond in time — skipping startup log stream.")
        else:
            print(f"Health check OK: {HEALTH_URL}")
            timeout = max(
                polling_seconds * startup_poll_logs + 120,
                polling_seconds * 2 + 60,
            )
            stream_startup_poll_logs(startup_poll_logs, timeout)
    else:
        if wait_for_server():
            print(f"Health check OK: {HEALTH_URL}")
        else:
            print("Warning: Server did not respond in time.")
        print(f"Tail logs:  python logs.py")
        print(f"Stop bot:   python stop.py")
        print(f"Log file:   {LOG_FILE}")


if __name__ == "__main__":
    main()
