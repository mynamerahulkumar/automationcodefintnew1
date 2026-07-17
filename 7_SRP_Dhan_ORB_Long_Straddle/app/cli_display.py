"""CLI dashboard helpers for Long Straddle ORB."""

from __future__ import annotations

from typing import Any

from app.utils import format_money


def build_startup_banner(
    config_summary: dict[str, Any],
    bot_status: str = "RUNNING",
    python_version: str | None = None,
) -> str:
    """Return the startup configuration banner."""
    import sys

    strategy = config_summary.get("strategy", {})
    trading = config_summary.get("trading", {})
    option_sel = config_summary.get("option_selection", {})
    order = config_summary.get("order", {})
    risk = config_summary.get("risk", {})
    bot = config_summary.get("bot", {})
    server = config_summary.get("server", {})
    security = config_summary.get("security", {})
    py_ver = python_version or sys.version.split()[0]

    lines = [
        "=" * 56,
        "",
        "SRP DHAN LONG STRADDLE ORB BOT",
        "",
        "=" * 56,
        "",
        "Bot Status",
        "",
        bot_status,
        "",
        "Strategy",
        "",
        str(strategy.get("name", "Long Straddle ORB")),
        "",
        "Underlying",
        "",
        str(trading.get("underlying", "")),
        "",
        "Underlying Security ID",
        "",
        str(security.get("security_id") or "-"),
        "",
        "Expiry",
        "",
        str(trading.get("expiry", "")),
        "",
        "Strike Type",
        "",
        str(option_sel.get("type", "ATM")),
        "",
        "Strike Offset",
        "",
        str(option_sel.get("strike_offset", 0)),
        "",
        "Entry Time",
        "",
        str(strategy.get("entry_time", "")),
        "",
        "Opening Range",
        "",
        f"{strategy.get('opening_range_minutes', 15)} Minutes",
        "",
        "Quantity",
        "",
        str(trading.get("quantity", "")),
        "",
        "Order Type",
        "",
        str(order.get("order_type", "LIMIT")),
        "",
        "Take Profit",
        "",
        f"{risk.get('take_profit_percent', '')}%",
        "",
        "Stop Loss",
        "",
        f"{risk.get('stop_loss_percent', '')}%",
        "",
        "Trailing",
        "",
        "Enabled" if risk.get("trailing_enabled", True) else "Disabled",
        "",
        "Polling",
        "",
        f"{bot.get('polling_interval_seconds', 30)} Seconds",
        "",
        "FastAPI Port",
        "",
        str(server.get("port", 7003)),
        "",
        "CSV Security Resolution",
        "",
        "Enabled",
        "",
        "Paper Trade",
        "",
        "YES" if bot.get("paper_trade") else "NO",
        "",
        "Python",
        "",
        py_ver,
    ]
    if sys.version_info < (3, 10):
        lines.extend(
            [
                "",
                "Note",
                "",
                "Python <3.10 — market data uses REST; upgrade to 3.10+ for live orders (dhanhq 2.2)",
            ]
        )
    lines.extend(
        [
            "",
            "=" * 56,
            "",
            "BOT STARTED SUCCESSFULLY",
            "",
            "=" * 56,
        ]
    )
    return "\n".join(lines)



def build_poll_dashboard(snapshot: dict[str, Any]) -> str:
    """Build the every-poll CLI dashboard block."""
    call = snapshot.get("call", {})
    put = snapshot.get("put", {})
    candle = snapshot.get("candle", {})

    rows = [
        ("Current Time", snapshot.get("last_poll_at") or "-"),
        ("Spot Price", format_money(snapshot.get("spot_price"))),
        ("ATM Strike", format_money(snapshot.get("atm_strike"), 0)),
        ("CALL Strike", format_money(call.get("strike"), 0)),
        ("PUT Strike", format_money(put.get("strike"), 0)),
        ("CALL Security ID", call.get("security_id") or "-"),
        ("PUT Security ID", put.get("security_id") or "-"),
        ("CALL LTP", format_money(call.get("current_price"))),
        ("PUT LTP", format_money(put.get("current_price"))),
        ("CALL Entry", format_money(call.get("entry_price"))),
        ("PUT Entry", format_money(put.get("entry_price"))),
        ("CALL PnL", format_money(call.get("pnl"))),
        ("PUT PnL", format_money(put.get("pnl"))),
        ("Combined PnL", format_money(snapshot.get("combined_pnl"))),
        ("ORB High", format_money(snapshot.get("orb_high"))),
        ("ORB Low", format_money(snapshot.get("orb_low"))),
        ("Candle Open", format_money(candle.get("open"))),
        ("Candle High", format_money(candle.get("high"))),
        ("Candle Low", format_money(candle.get("low"))),
        ("Candle Close", format_money(candle.get("close"))),
        ("Breakout Status", snapshot.get("breakout_status") or "-"),
        ("Phase", snapshot.get("phase") or "-"),
        ("CALL Status", call.get("status") or "-"),
        ("PUT Status", put.get("status") or "-"),
        ("CALL Trailing Stop", format_money(call.get("trailing_stop"))),
        ("PUT Trailing Stop", format_money(put.get("trailing_stop"))),
        ("CALL Target", format_money(call.get("target"))),
        ("PUT Target", format_money(put.get("target"))),
        ("CALL Stop Loss", format_money(call.get("stop_loss"))),
        ("PUT Stop Loss", format_money(put.get("stop_loss"))),
        ("API Response Time", f"{snapshot.get('api_response_ms') or '-'} ms"),
        ("Next Poll", snapshot.get("next_poll_at") or "-"),
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
        f"breakout:{snapshot.get('breakout_status')} | "
        f"CE:{format_money(call.get('current_price'))} "
        f"PnL:{format_money(call.get('pnl'))} | "
        f"PE:{format_money(put.get('current_price'))} "
        f"PnL:{format_money(put.get('pnl'))} | "
        f"combined:{format_money(snapshot.get('combined_pnl'))} | "
        f"ORB:{format_money(snapshot.get('orb_high'))}/"
        f"{format_money(snapshot.get('orb_low'))}"
    )
