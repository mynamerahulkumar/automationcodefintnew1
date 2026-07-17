# SRP Dhan Long Straddle EMA Confirmation

Production-ready algorithmic trading bot for Dhan Broker.

**Strategy:** Buy ATM CE + ATM PE at entry time, then use EMA 9/21 crossover as confirmation — exit the opposite leg and trail the remaining leg.

## Quick start

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN
```

Edit `config/config.yaml`:

- Keep `bot.paper_trade: true` until ready for live orders
- Set `security.security_id` (NIFTY=`13`) — required on 1GB AWS VMs
- Align `ema.timeframe` with your chart (`5m` / `15m` / `1d`)

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

## Low-RAM / AWS notes

- Poll path uses REST only (no `dhanhq` import) — works on Python 3.9+
- Orders need Python 3.10+ (or pin `dhanhq==2.0.2`)
- Credentials live in `.env` only — never in `config.yaml`
- EMA uses TradingView-style SMA seed for chart alignment

## Layout

```
app/                 # FastAPI, bot, strategy, REST market data
config/config.yaml
.env.example
security_id/         # api-scrip-master.csv (option lookup at entry)
start.py stop.py logs.py
Dhan_SRP.py
```
