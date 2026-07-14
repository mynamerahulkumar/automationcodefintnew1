# SRP Dhan EMA Crossover Trading Engine

Production-ready Python FastAPI application that automatically trades Dhan stocks and options using an **EMA Crossover** strategy. Designed for continuous 24×7 execution on a local machine or a low-cost AWS VM (1 GB RAM).

## Project Structure

```
app/
  api.py              # FastAPI routes (/health, /status, /reload-config, /place-order)
  bot.py              # Trading bot orchestrator
  strategy/           # Pluggable strategies + factory
    __init__.py       # Strategy factory (get_strategy)
    ema_crossover.py  # EMA crossover signal logic
  order_service.py    # LIMIT order placement
  dhan_client.py      # Dhan_SRP wrapper (lazy import)
  config_loader.py    # YAML config loader
  security_master.py  # CSV security ID lookup
  market_data.py      # Candle fetching via Dhan API
  scheduler.py        # Polling loop
  state.py            # In-memory bot state
  logger.py           # Rotating file logs
  utils.py            # Shared helpers
config/config.yaml    # All trading parameters
security_id/api-scrip-master.csv
Dhan_SRP.py           # Dhan broker layer (do not rewrite)
docs/
  project_requirements.md
  srp_dhan_helper.md
start.py              # Start engine on port 7001
stop.py               # Graceful shutdown
logs.py               # tail -f logs/trading.log
run/bot.pid           # PID file (auto-managed)
logs/trading.log      # Application log
```

## Setup

See **[setup.md](setup.md)** for full Windows, macOS, and Linux installation and run instructions.

Quick start (macOS/Linux):

cd 2_EMA_Crossover_Order_Stock
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `config/config.yaml`:

```yaml
broker:
  client_id: "YOUR_CLIENT_ID"
  access_token: "YOUR_ACCESS_TOKEN"

trading:
  exchange: NSE
  segment: EQUITY          # EQUITY or OPTION
  stock_name: HDFCBANK
  security_id: ""          # optional — auto-resolved from CSV
  quantity: 1
  product_type: INTRADAY
  order_type: LIMIT
  transaction_type: BUY
  limit_price: 0           # 0 = use LTP for auto-trades

strategy:
  name: EMA_CROSSOVER
  timeframe: 5m
  fast_ema: 9
  slow_ema: 21
  polling_seconds: 30

risk:
  target_percent: 2        # placeholder — exit logic not yet implemented
  stoploss_percent: 1
  trailing_sl: false

bot:
  paper_trade: true        # set false for live orders
  one_position_only: true
  cooldown_seconds: 60
  log_level: INFO
  startup_poll_logs: 2     # polls to show on CLI at start (0 = skip)
```

Credentials can also be set via environment variables:

```bash
export DHAN_CLIENT_ID="..."
export DHAN_ACCESS_TOKEN="..."
```

Security IDs are resolved automatically from `security_id/api-scrip-master.csv` using `stock_name`.

## Run

```bash
python start.py      # starts on 0.0.0.0:7001, prints startup banner
python logs.py       # stream logs/trading.log
python stop.py       # graceful shutdown, removes run/bot.pid
```

Running `python start.py` again automatically stops the previous instance before starting a new one.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `Running` |
| GET | `/status` | Bot status, EMA values, signal, last trade, risk config |
| POST | `/reload-config` | Hot-reload `config.yaml` |
| POST | `/place-order` | Manual LIMIT order from config |

### Example: Check Status

```bash
curl http://127.0.0.1:7001/status
```

## Strategy Logic

**EMA Crossover** (configurable fast/slow periods and timeframe):

- **BUY** — Fast EMA crosses above Slow EMA (confirmed candle close)
- **SELL** — Fast EMA crosses below Slow EMA (confirmed candle close)

Guards:
- Duplicate signals on the same candle are ignored
- `cooldown_seconds` prevents rapid re-entry after a trade
- `one_position_only` blocks BUY when already LONG, SELL when FLAT
- `paper_trade: true` logs signals without sending orders to Dhan

## AWS 1 GB VM Deployment

```bash
# On the VM
git clone <repo>
cd 2_EMA_Crossover_Order_Stock
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Set credentials via env vars (recommended)
export DHAN_CLIENT_ID="..."
export DHAN_ACCESS_TOKEN="..."

# Start with paper trading first
python start.py
```

Performance optimizations:
- Lazy `Dhan_SRP` import (~100 MB saved at cold start)
- CSV security index built once at startup (stdlib `csv`)
- EMA computed on plain float lists (no DataFrame in poll loop)
- Single Uvicorn worker, rotating logs (1 MB × 3)

## Extending with New Strategies

Add a new file under `app/strategy/` and register it in `app/strategy/__init__.py`:

```python
STRATEGIES = {
    "EMA_CROSSOVER": EmaCrossoverStrategy,
    "RSI": RsiStrategy,          # future
}
```

Select the strategy in `config.yaml` under `strategy.name`.

## Dhan API Reference

See [`docs/srp_dhan_helper.md`](docs/srp_dhan_helper.md) for the full `Dhan_SRP.py` API reference. Do not rewrite Dhan API calls — use existing helper methods.

## Notes

- TP/SL values are stored in config and exposed via `/status` but **exit management is not yet implemented**
- Only LIMIT orders are supported
- NSE market hours: Mon–Fri 9:15 AM – 3:30 PM IST
- Whitelist your server IP in Dhan settings for API access
