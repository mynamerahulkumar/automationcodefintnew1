"""CLI formatting helpers for poll summaries."""

from __future__ import annotations


def format_price(value: float | None) -> str:
    """Format a price for display."""
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def format_ema(value: float | None) -> str:
    """Format an EMA value for display."""
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def ema_trend_label(fast_ema: float | None, slow_ema: float | None) -> str:
    """Return a short trend label comparing fast and slow EMA."""
    if fast_ema is None or slow_ema is None:
        return "N/A"
    if fast_ema > slow_ema:
        return "Bullish (Fast EMA > Slow EMA)"
    if fast_ema < slow_ema:
        return "Bearish (Fast EMA < Slow EMA)"
    return "Neutral (Fast EMA = Slow EMA)"


def build_poll_summary_log(
    *,
    symbol: str,
    segment: str,
    fast_period: int,
    slow_period: int,
    current_price: float | None,
    fast_ema: float | None,
    slow_ema: float | None,
    signal: str | None,
    candle_time: str | None,
) -> str:
    """Build a single-line poll summary for logs and CLI streaming."""
    signal_text = signal if signal else "None"
    candle_text = candle_time if candle_time else "N/A"
    trend = ema_trend_label(fast_ema, slow_ema)
    return (
        f"POLL SUMMARY | {symbol} ({segment}) | "
        f"LTP: {format_price(current_price)} | "
        f"Fast EMA({fast_period}): {format_ema(fast_ema)} | "
        f"Slow EMA({slow_period}): {format_ema(slow_ema)} | "
        f"Trend: {trend} | "
        f"Signal: {signal_text} | "
        f"Candle: {candle_text}"
    )


def print_poll_summary_block(
    *,
    poll_number: int,
    symbol: str,
    segment: str,
    fast_period: int,
    slow_period: int,
    current_price: float | None,
    fast_ema: float | None,
    slow_ema: float | None,
    signal: str | None,
    candle_time: str | None,
) -> None:
    """Print a readable poll summary block to the CLI."""
    signal_text = signal if signal else "None"
    candle_text = candle_time if candle_time else "N/A"
    trend = ema_trend_label(fast_ema, slow_ema)
    price_label = "Option Price (LTP)" if segment.upper() == "OPTION" else "Stock Price (LTP)"

    print()
    print(f"  Poll #{poll_number} — {symbol} [{segment}]")
    print(f"  {price_label:<22}: {format_price(current_price)}")
    print(f"  Fast EMA ({fast_period}){' ' * (14 - len(str(fast_period)))}: {format_ema(fast_ema)}")
    print(f"  Slow EMA ({slow_period}){' ' * (14 - len(str(slow_period)))}: {format_ema(slow_ema)}")
    print(f"  Trend                 : {trend}")
    print(f"  Signal                : {signal_text}")
    print(f"  Candle Time           : {candle_text}")
    print()
