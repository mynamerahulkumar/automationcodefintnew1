# SRP Dhan Long Straddle EMA Confirmation

Production-ready algorithmic trading bot for Dhan Broker.

**Strategy:** Buy ATM CE + ATM PE at entry time, then use EMA 9/21 crossover as confirmation — exit the opposite leg and trail the remaining leg.

## Quick start

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Edit `config/config.yaml` (or set `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN`):

- Keep `bot.paper_trade: true` until you are ready for live orders
- Set `trading.underlying`, `quantity`, `entry_time`, EMA and risk params

```bash
python start.py
python logs.py
python stop.py
```

FastAPI runs on `http://0.0.0.0:7003`

| Endpoint | Description |
|----------|-------------|
| `GET /` | Health / info |
| `GET /status` | Strategy, EMA, positions, PnL |
| `GET /config` | Redacted config |
| `GET /logs` | Recent log lines |
| `POST /stop` | Graceful square-off + stop |

## Strategy flow

1. Wait until `strategy.entry_time`
2. Buy ATM CE + ATM PE (configurable quantity / strike type)
3. Monitor EMA9 / EMA21 on the underlying
4. Bullish cross → exit PUT, trail CALL
5. Bearish cross → exit CALL, trail PUT
6. Remaining leg uses % target, % SL, trailing stop, and square-off time

## Layout

```
app/                 # FastAPI, bot, strategy, services
config/config.yaml
security_id/         # api-scrip-master.csv
start.py stop.py logs.py
Dhan_SRP.py
```
