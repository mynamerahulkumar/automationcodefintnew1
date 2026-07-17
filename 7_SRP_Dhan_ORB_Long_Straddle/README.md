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

## Low-RAM / AWS notes

- Market data (spot, option LTP, intraday candles) uses a **REST client** — does **not** import `dhanhq` on poll
- Set `security.security_id` (NIFTY=`13`) so order client skips loading `api-scrip-master.csv` into pandas
- Credentials live in **`.env`** only (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`)
- Python **3.10+** recommended for live order placement (`dhanhq` 2.2 uses `match`/`case`)

## Project structure

```
app/
  api.py
  bot.py
  dhan_rest.py           # REST LTP + candles (poll path)
  dhan_client.py         # lite REST + lazy Dhan_SRP for orders
  market_data.py
  option_selector.py
  order_service.py
  strategy/long_straddle_orb.py
  ...
config/config.yaml
.env.example
start.py / stop.py / logs.py
```

## Quick start

See **[setup.md](setup.md)** for full install steps.

```bash
cd 7_SRP_Dhan_ORB_Long_Straddle
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with real DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN
python start.py
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
security:
  symbol: NIFTY
  security_id: "13"    # keep set on 1GB VMs

strategy:
  entry_time: "09:15"
  opening_range_minutes: 15
  square_off_time: "15:15"

option_selection:
  type: ATM
  strike_offset: 0

bot:
  paper_trade: true    # start dry-run first
```

CE/PE security IDs are resolved from `security_id/api-scrip-master.csv` via streaming CSV (not full pandas load on poll).
