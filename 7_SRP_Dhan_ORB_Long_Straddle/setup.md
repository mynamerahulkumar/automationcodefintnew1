# Setup — SRP Dhan Long Straddle ORB Bot

## Requirements

- Python 3.10+ recommended (3.9+ can poll via REST; live orders need 3.10+ or `dhanhq==2.0.2`)
- Dhan API credentials in `.env`
- Static IP whitelisted on Dhan for order APIs
- Active Dhan data plan for LTP / intraday candles

## Install (macOS / Linux)

```bash
cd 7_SRP_Dhan_ORB_Long_Straddle
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
DHAN_CLIENT_ID=YOUR_CLIENT_ID
DHAN_ACCESS_TOKEN=YOUR_ACCESS_TOKEN
```

## Install (Windows)

```bat
cd 7_SRP_Dhan_ORB_Long_Straddle
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env
```

## Configure

1. Credentials: **only** in `.env` (never in `config.yaml`)
2. Keep underlying security id set for 1GB hosts:

```yaml
security:
  symbol: NIFTY
  security_id: "13"
```

3. Prefer paper mode first:

```yaml
bot:
  paper_trade: true
  polling_interval_seconds: 30
```

## Run

```bash
python start.py
python logs.py
python stop.py
```

`start.py` prints Python version and maps common failures (DH-901, OOM, dhanhq syntax) to clear `ERROR:` lines.

## Verify

```bash
curl http://127.0.0.1:7003/health
curl http://127.0.0.1:7003/status
curl http://127.0.0.1:7003/config
```

## AWS Lightsail / EC2 (1 GB)

1. Create `.env` on the VM (`chmod 600 .env`)
2. Confirm `python3 --version`
   - **&lt; 3.10**: REST polling OK; for orders upgrade Python or `pip install 'dhanhq==2.0.2'`
   - **≥ 3.10**: full stack OK
3. Keep `security.security_id` set so order client skips loading the instrument CSV into pandas
4. Restart after token refresh: `python stop.py && python start.py`

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Credentials missing | Copy `.env.example` → `.env` and set both vars |
| DH-901 / Invalid Authentication | Refresh `DHAN_ACCESS_TOKEN` in `.env`, restart |
| DH-902 | Subscribe to Dhan Data APIs |
| `invalid syntax (_super_order.py)` | Use Python 3.10+ or pin `dhanhq==2.0.2`; polls already use REST |
| MemoryError | Keep `security.security_id`; do not force full CSV into pandas |
| Option not found | Refresh `api-scrip-master.csv`; check weekly expiry / strike |
