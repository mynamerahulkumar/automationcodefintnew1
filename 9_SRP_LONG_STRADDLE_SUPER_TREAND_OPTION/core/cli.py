"""CLI dashboard helpers for Long Straddle Supertrend Confirmation."""

from __future__ import annotations

from typing import Any

from core.utils import format_money


def build_startup_banner(config_summary: dict[str, Any], bot_status: str = "RUNNING") -> str:
    """Return the startup configuration banner."""
    strategy = config_summary.get("strategy", {})
    trading = config_summary.get("trading", {})
    option_sel = config_summary.get("strike_selection", {})
    order = config_summary.get("order", {})
    risk = config_summary.get("risk", {})
    trail = config_summary.get("trail", {})
    bot = config_summary.get("bot", {})
    server = config_summary.get("server", {})
    st = config_summary.get("supertrend", {})

    trail_label = "Disabled"
    if trail.get("enabled", True):
        mode = str(trail.get("mode", "percent")).lower()
        if mode == "points":
            trail_label = f"Enabled ({trail.get('points', '')} pts)"
        else:
            trail_label = f"Enabled ({trail.get('percent', '')}%)"

    lines = [
        "=" * 56,
        "",
        "Configuration Loaded Successfully",
        "",
        "=" * 56,
        "",
        "LONG STRADDLE SUPERTREND BOT",
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
        "Segment",
        "",
        str(trading.get("segment", "OPTION")),
        "",
        "Underlying",
        "",
        str(trading.get("underlying", "")),
        "",
        "Expiry",
        "",
        str(trading.get("expiry", "")),
        "",
        "Strike Selection",
        "",
        str(option_sel.get("type", "ATM")),
        "",
        "Quantity",
        "",
        str(trading.get("quantity", "")),
        "",
        "SL",
        "",
        f"{risk.get('stop_loss_percent', '')}%",
        "",
        "TP",
        "",
        f"{risk.get('take_profit_percent', '')}%",
        "",
        "Trailing",
        "",
        trail_label,
        "",
        "Polling Interval",
        "",
        f"{bot.get('polling_interval_seconds', 30)} Seconds",
        "",
        "Supertrend Length",
        "",
        str(st.get("length", 10)),
        "",
        "Multiplier",
        "",
        str(st.get("multiplier", 3)),
        "",
        "Entry Time",
        "",
        str(strategy.get("entry_time", "")),
        "",
        "Port",
        "",
        str(server.get("port", 7003)),
        "",
        "Order Type",
        "",
        str(order.get("order_type", "LIMIT")),
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
    """Build the every-poll CLI dashboard block matching requirements layout."""
    call = snapshot.get("call", {})
    put = snapshot.get("put", {})
    remaining = snapshot.get("remaining_leg") or "BOTH"
    exited = snapshot.get("exited_leg") or "-"
    trail_stop = None
    if remaining == "CALL":
        trail_stop = call.get("trailing_stop")
    elif remaining == "PUT":
        trail_stop = put.get("trailing_stop")
    else:
        trail_stop = call.get("trailing_stop") or put.get("trailing_stop")

    lines = [
        "",
        "=" * 50,
        "",
        "LONG STRADDLE SUPERTREND BOT",
        "",
        "=" * 50,
        "",
        "Time",
        "",
        str(snapshot.get("last_poll_at") or "-"),
        "",
        "Underlying",
        "",
        str(snapshot.get("underlying") or "-"),
        "",
        "Spot",
        "",
        format_money(snapshot.get("spot_price")),
        "",
        "ATM",
        "",
        format_money(snapshot.get("atm_strike"), 0),
        "",
        "CALL",
        "",
        str(call.get("status") or "-"),
        "",
        "LTP",
        "",
        format_money(call.get("current_price")),
        "",
        "PUT",
        "",
        str(put.get("status") or "-"),
        "",
        "LTP",
        "",
        format_money(put.get("current_price")),
        "",
        "Supertrend",
        "",
        str(snapshot.get("supertrend_direction") or "-"),
        "",
        "ST Value",
        "",
        format_money(snapshot.get("supertrend_value")),
        "",
        "Remaining Position",
        "",
        str(remaining),
        "",
        "Exited Position",
        "",
        str(exited),
        "",
        "Current Profit",
        "",
        format_money(snapshot.get("combined_pnl")),
        "",
        "Trailing Stop",
        "",
        format_money(trail_stop),
        "",
        "Polling Count",
        "",
        str(snapshot.get("poll_count") or "-"),
        "",
        "Next Poll",
        "",
        f"{snapshot.get('poll_interval') or '-'} sec",
        "",
        "=" * 50,
    ]
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
        f"st:{format_money(snapshot.get('supertrend_value'))} "
        f"{snapshot.get('supertrend_direction')} | "
        f"CE:{format_money(call.get('current_price'))} "
        f"PnL:{format_money(call.get('pnl'))} | "
        f"PE:{format_money(put.get('current_price'))} "
        f"PnL:{format_money(put.get('pnl'))} | "
        f"combined:{format_money(snapshot.get('combined_pnl'))} | "
        f"leg:{snapshot.get('remaining_leg') or 'BOTH'}"
    )
