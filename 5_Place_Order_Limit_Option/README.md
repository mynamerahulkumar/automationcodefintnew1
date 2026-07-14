# Dhan Limit Order FastAPI Service

Lightweight FastAPI service to place **LIMIT** stock and option orders on Dhan using configuration from `config/config.yaml`.

## Project Structure

```
app/
  api.py              # FastAPI routes
  order_service.py    # Order placement logic
  dhan_client.py      # Dhan_SRP wrapper
  config_loader.py    # YAML config loader
  utils.py            # Security master lookup
  logger.py           # Rotating logs
config/config.yaml    # Trading configuration
security_id/api-scrip-master.csv
Dhan_SRP.py           # Dhan broker layer (reference)
start.py              # Start server on port 7001
stop.py               # Graceful shutdown
logs.py               # tail -f logs/trading.log
requirements.txt
```

## Setup

```bash
cd 1_Place_Limit_Order_Stock
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Edit `config/config.yaml`:

```yaml
dhan:
  client_id: "YOUR_CLIENT_ID"
  access_token: "YOUR_ACCESS_TOKEN"

trading:
  segment: EQUITY          # EQUITY or OPTION
  exchange: NSE
  stock_name: HDFCBANK
  security_id: ""          # optional override
  quantity: 1
  product_type: INTRADAY
  transaction_type: BUY
  order_type: LIMIT
  limit_price: 1890.50

risk:
  target_percent: 2
  stoploss_percent: 1

cloud:
  log_level: INFO
  dry_run: true            # set false for live orders
  console_log: false       # true for local dev, false on AWS 1GB VM
```

Credentials can also be set via environment variables:

```bash
export DHAN_CLIENT_ID="..."
export DHAN_ACCESS_TOKEN="..."
```

Security IDs are resolved automatically from `security_id/api-scrip-master.csv` using `stock_name`. For options, also set `expiry`, `strike`, and `option_type`.

## Run on Cloud

```bash
python start.py      # starts on 0.0.0.0:7001
python logs.py       # view logs/trading.log
python stop.py       # graceful shutdown
```

## API Endpoints

### Health

```bash
curl http://localhost:7001/health
```

Response:

```json
{"status": "running"}
```

### Place Order

```bash
curl -X POST http://localhost:7001/place-order
```

Reads all order parameters from `config/config.yaml`, resolves security ID, and places a LIMIT order.

Success response:

```json
{
  "status": "success",
  "order_id": "...",
  "security_id": "1333",
  "symbol": "HDFCBANK",
  "risk": {"target_percent": 2, "stoploss_percent": 1}
}
```

With `cloud.dry_run: true`, returns validation/preview without placing a live order.

### Reload Config

```bash
curl -X POST http://localhost:7001/reload-config
```

Reloads `config/config.yaml` without restarting the server.

## Low-Memory Optimizations (1GB AWS VM)

- **No duplicate CSV load** — security lookup uses stdlib `csv` with a compact equity index (~1MB); full pandas load happens only once inside `Dhan_SRP` on first order
- **Lazy Dhan client** — `Dhan_SRP` (pandas/numpy/mibian) imports only when `/place-order` is called, not at startup
- **Single worker** — uvicorn runs with `--workers 1` and limited concurrency
- **File-only logging on cloud** — set `cloud.console_log: false` (default); use `python logs.py` to tail logs
- **Smaller log rotation** — 1MB × 3 backup files

For local development, set `cloud.console_log: true` in `config/config.yaml`.

## Notes

- Only **LIMIT** orders are supported in this version.
- TP/SL values are stored in config for future use; bracket logic is not implemented yet.
- Live order placement requires Dhan static IP whitelisting.
- Uses `Dhan_SRP.py` for all Dhan API interactions.

## References

- `Dhan_SRP.py` — broker and order methods
- `srp_dhan_helper.md` — usage examples and payloads
