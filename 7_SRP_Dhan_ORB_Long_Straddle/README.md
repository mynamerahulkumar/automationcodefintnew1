# SRP Dhan Long Straddle ORB Bot

Production-ready Python FastAPI bot that buys an ATM (or ITM/OTM) **long straddle** at a configured entry time, builds an **Opening Range**, then exits the losing leg on breakout and trails the winner.

Designed for low-memory AWS Lightsail / EC2 (1 GB RAM) and local Windows / macOS / Linux.

## Strategy

1. At `entry_time` (default 09:15) — BUY ATM CALL + BUY ATM PUT (LIMIT + buffer)
2. During `opening_range_minutes` (default 15) — track ORB HIGH / ORB LOW on spot
3. Breakout:
   - Spot > ORB HIGH → exit PUT, keep CALL, enable CALL trailing stop
   - Spot < ORB LOW → exit CALL, keep PUT, enable PUT trailing stop
4. Exit remaining leg on trailing SL, target, hard SL, square-off time, or `stop.py`

## Project structure

```
app/
  api.py                 # FastAPI /, /health, /status, /config
  bot.py                 # Poll orchestrator + state machine
  strategy/long_straddle_orb.py
  option_selector.py
  order_service.py
  market_data.py
  security_master.py
  config_loader.py
  dhan_client.py
  state.py
  scheduler.py
  cli_display.py
  logger.py
  utils.py
config/config.yaml
security_id/api-scrip-master.csv
Dhan_SRP.py
start.py                 # port 7003
stop.py
logs.py
```

## Quick start

See **[setup.md](setup.md)** for full install steps.

```bash
cd 7_SRP_Dhan_ORB_Long_Straddle
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Edit `config/config.yaml` — set `dhan.client_id` / `dhan.access_token` (or `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN`).

```bash
python start.py
python logs.py
python stop.py
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Bot info |
| `GET /health` | Health check |
| `GET /status` | Live phase, ORB, dual-leg PnL |
| `GET /config` | Config summary (no secrets) |

Default: `http://localhost:7003`

## Configuration highlights

```yaml
strategy:
  entry_time: "09:15"
  opening_range_minutes: 15
  square_off_time: "15:15"

option_selection:
  type: ATM          # ATM | ITM | OTM
  strike_offset: 0

order:
  order_type: LIMIT
  limit_buffer: 0.50

risk:
  stop_loss_percent: 25
  take_profit_percent: 50
  trailing_enabled: true
  trailing_percent: 10

bot:
  paper_trade: false   # true = dry-run orders
```

Security IDs for CE/PE are resolved automatically from `security_id/api-scrip-master.csv` when blank.

## Notes

- No WebSockets — polling only
- Single instance via `run/bot.pid`
- Rotating logs in `logs/bot.log`
- Reuses helpers from `Dhan_SRP.py` (do not rewrite)
