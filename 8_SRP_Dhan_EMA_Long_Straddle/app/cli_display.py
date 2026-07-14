"""CLI dashboard helpers for Long Straddle EMA Confirmation."""

from __future__ import annotations

from typing import Any

from app.utils import format_money


def build_startup_banner(config_summary: dict[str, Any], bot_status: str = "RUNNING") -> str:
    """Return the startup configuration banner."""
    strategy = config_summary.get("strategy", {})
    trading = config_summary.get("trading", {})
    option_sel = config_summary.get("option_selection", {})
    order = config_summary.get("order", {})
    risk = config_summary.get("risk", {})
    bot = config_summary.get("bot", {})
    server = config_summary.get("server", {})
    ema = config_summary.get("ema", {})

    lines = [
        "=" * 56,
        "",
        "SRP Trading Bot",
        "",
        "Strategy",
        "",
        str(strategy.get("name", "Long Straddle EMA Confirmation")),
        "",
        "=" * 56,
        "",
        "Bot Status",
        "",
        bot_status,
        "",
        "Broker",
        "",
        "Dhan",
        "",
        "Exchange",
        "",
        str(trading.get("exchange", "NSE")),
        "",
        "Symbol",
        "",
        str(trading.get("underlying", "")),
        "",
        "Expiry",
        "",
        str(trading.get("expiry", "")),
        "",
        "Quantity",
        "",
        str(trading.get("quantity", "")),
        "",
        "Strike",
        "",
        str(option_sel.get("type", "ATM")),
        "",
        "EMA",
        "",
        f"{ema.get('fast', 9)} / {ema.get('slow', 21)}",
        "",
        "Entry Time",
        "",
        str(strategy.get("entry_time", "")),
        "",
        "Exit Time",
        "",
        str(strategy.get("square_off_time", "")),
        "",
        "Order Type",
        "",
        str(order.get("order_type", "LIMIT")),
        "",
        "Target",
        "",
        f"{risk.get('take_profit_percent', '')}%",
        "",
        "SL",
        "",
        f"{risk.get('stop_loss_percent', '')}%",
        "",
        "Trailing",
        "",
        (
            f"Enabled ({risk.get('trailing_percent', '')}%)"
            if risk.get("trailing_enabled", True)
            else "Disabled"
        ),
        "",
        "Polling Interval",
        "",
        f"{bot.get('polling_interval_seconds', 30)} Seconds",
        "",
        "Server Port",
        "",
        str(server.get("port", 7003)),
        "",
        "Log File",
        "",
        "logs/bot.log",
        "",
        "Paper Trade",
        "",
        "YES" if bot.get("paper_trade") else "NO",
        "",
        "=" * 56,
        "",
        "Bot Started Successfully",
        "",
        "=" * 56,
    ]
    return "\n".join(lines)


def build_poll_dashboard(snapshot: dict[str, Any]) -> str:
    """Build the every-poll CLI dashboard block."""
    call = snapshot.get("call", {})
    put = snapshot.get("put", {})

    rows = [
        ("Current Time", snapshot.get("last_poll_at") or "-"),
        ("Current Poll", snapshot.get("poll_count") or "-"),
        ("Current Price", format_money(snapshot.get("spot_price"))),
        ("EMA 9", format_money(snapshot.get("fast_ema"), 4)),
        ("EMA 21", format_money(snapshot.get("slow_ema"), 4)),
        ("EMA Trend", snapshot.get("ema_trend") or "-"),
        ("Current Position", snapshot.get("phase") or "-"),
        ("ATM Strike", format_money(snapshot.get("atm_strike"), 0)),
        ("CE Status", call.get("status") or "-"),
        ("PE Status", put.get("status") or "-"),
        ("Entry Price CE", format_money(call.get("entry_price"))),
        ("Entry Price PE", format_money(put.get("entry_price"))),
        ("Current CE LTP", format_money(call.get("current_price"))),
        ("Current PE LTP", format_money(put.get("current_price"))),
        ("Remaining Leg", snapshot.get("remaining_leg") or "-"),
        ("Current MTM", format_money(snapshot.get("combined_pnl"))),
        ("CE Target", format_money(call.get("target"))),
        ("PE Target", format_money(put.get("target"))),
        ("CE Stoploss", format_money(call.get("stop_loss"))),
        ("PE Stoploss", format_money(put.get("stop_loss"))),
        ("CE Trailing Stop", format_money(call.get("trailing_stop"))),
        ("PE Trailing Stop", format_money(put.get("trailing_stop"))),
        ("Polling Interval", f"{snapshot.get('poll_interval') or '-'} s"),
        ("API Status", "OK" if not snapshot.get("last_error") else "ERROR"),
        ("Server Status", snapshot.get("bot_status") or "-"),
        ("Memory Usage", f"{snapshot.get('memory_mb') or '-'} MB"),
        ("CPU Usage", f"{snapshot.get('cpu_percent') or '-'} %"),
        ("Next Poll", snapshot.get("next_poll_at") or "-"),
        ("API Response Time", f"{snapshot.get('api_response_ms') or '-'} ms"),
    ]

    lines = ["", "-" * 56, f"POLL #{snapshot.get('poll_count', 0)}", "-" * 56]
    for label, value in rows:
        lines.append(f"{label:<22}: {value}")
    lines.append("-" * 56)
    return "\n".join(lines)


def build_poll_summary_log(snapshot: dict[str, Any]) -> str:
    """Compact single-line poll summary for the log file."""
    call = snapshot.get("call", {})
    put = snapshot.get("put", {})
    return (
        "POLL SUMMARY | "
        f"{snapshot.get('underlying')} | "
        f"spot:{format_money(snapshot.get('spot_price'))} | "
        f"phase:{snapshot.get('phase')} | "
        f"ema:{format_money(snapshot.get('fast_ema'), 2)}/"
        f"{format_money(snapshot.get('slow_ema'), 2)} "
        f"{snapshot.get('ema_trend')} | "
        f"CE:{format_money(call.get('current_price'))} "
        f"PnL:{format_money(call.get('pnl'))} | "
        f"PE:{format_money(put.get('current_price'))} "
        f"PnL:{format_money(put.get('pnl'))} | "
        f"combined:{format_money(snapshot.get('combined_pnl'))} | "
        f"leg:{snapshot.get('remaining_leg') or 'BOTH'}"
    )
