#!/usr/bin/env python3
"""Start the SRP Dhan Long Straddle ORB bot on port 7003."""

from __future__ import annotations

import os
import re
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
LOG_MESSAGE_PATTERN = re.compile(
    r"^(ERROR|WARNING):\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+:(.*)$"
)


def print_startup_banner() -> None:
    from app.cli_display import build_startup_banner
    from app.config_loader import get_config_loader

    loader = get_config_loader()
    loader.load()
    print(
        build_startup_banner(
            loader.summary(),
            bot_status="RUNNING",
            python_version=sys.version.split()[0],
        )
    )


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
        if ":" in message:
            message = message.split(":", 2)[-1].strip()

    lowered_msg = message.lower()

    if "dh-901" in lowered or "invalid_authentication" in lowered:
        return "Dhan auth failed (DH-901) — refresh DHAN_ACCESS_TOKEN in .env"
    if "dh-902" in lowered or "not subscribed to data apis" in lowered:
        return (
            "Dhan Data API not subscribed (DH-902) — enable Data APIs on "
            "web.dhan.co to fetch LTP/candles"
        )
    if "memoryerror" in lowered_msg:
        return (
            "Out of memory — keep security.security_id in config.yaml; "
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
    if "broker credentials missing" in lowered_msg:
        return "Broker credentials missing — set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env"
    if "failed to fetch spot" in lowered_msg or "ltp fetch failed" in lowered_msg:
        return message
    if "unhandled error in poll cycle" in lowered_msg:
        detail = message.split("Unhandled error in poll cycle", 1)[-1].lstrip(": ").strip()
        if detail:
            return f"Poll cycle failed — {detail}"
        return "Poll cycle failed — check logs/bot.log for details."
    if is_error:
        return message
    if is_warning and ("empty candle" in lowered_msg or "orb candle" in lowered_msg):
        return message
    return None


def stream_cli_updates(duration_seconds: float) -> None:
    """Stream poll dashboards and surface real errors from the log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_FILE.exists():
        LOG_FILE.touch()

    deadline = time.time() + duration_seconds
    polls_seen = 0
    last_error: str | None = None

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

                error_text = _extract_poll_error(line)
                if error_text and error_text != last_error:
                    last_error = error_text
                    print(f"  ERROR: {error_text}")

                if POLL_LOG_MARKER in line:
                    polls_seen += 1
                    print(line, end="")
                elif CLI_DASHBOARD_MARKER in line:
                    print(line, end="")
                    for _ in range(40):
                        nxt = handle.readline()
                        if not nxt:
                            break
                        print(nxt, end="")
                        err = _extract_poll_error(nxt)
                        if err and err != last_error:
                            last_error = err
                            print(f"  ERROR: {err}")
                        if POLL_LOG_MARKER in nxt:
                            polls_seen += 1
                            break
        except KeyboardInterrupt:
            pass

    print("=" * 56)
    if polls_seen == 0 and last_error:
        print(f"Startup polls failed: {last_error}")
        print("See full details in logs/bot.log and logs/uvicorn.out")
    elif polls_seen == 0:
        print("No polls logged yet — bot may still be starting.")
        print("See logs/bot.log and logs/uvicorn.out")
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
        try:
            loader.get_broker_credentials()
        except Exception as cred_exc:
            print(f"ERROR: {cred_exc}")
            print("Copy .env.example → .env and set DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN.")
            sys.exit(1)
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
    print(f"Started SRP Long Straddle ORB bot on {host}:{port} (PID {process.pid})")

    if bool(bot_cfg.get("always_refresh_cli", True)):
        if not wait_for_server(port):
            print("Warning: Server did not respond in time — skipping startup log stream.")
            print("See logs/uvicorn.out for details.")
        else:
            stream_cli_updates(max(polling_seconds * 3 + 30, 60))
    else:
        print("Tail logs:      python logs.py")
        print(f"Log file:       {LOG_FILE}")


if __name__ == "__main__":
    main()
