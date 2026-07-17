# Setup — Long Straddle EMA Confirmation

## 1. Environment

```bash
cd 8_SRP_Dhan_EMA_Long_Straddle
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Credentials (`.env` only)

```env
DHAN_CLIENT_ID=your_client_id
DHAN_ACCESS_TOKEN=your_access_token
```

Do not put tokens in `config.yaml`. After changing `.env`, restart:

```bash
python stop.py && python start.py
```

On AWS: create `.env` on the VM, `chmod 600 .env`.

## 3. Config

- `security.security_id: "13"` for NIFTY (required on 1GB hosts)
- `ema.timeframe: 5m` (or `1d` to match daily charts)
- `bot.paper_trade: true` until dry-run succeeds

## 4. Run

```bash
python start.py
```

API: `http://127.0.0.1:7003/status`

## 5. Common errors

| Console message | Fix |
|-----------------|-----|
| DH-901 | Refresh `DHAN_ACCESS_TOKEN` in `.env` |
| DH-902 | Enable Dhan Data APIs |
| MemoryError | Keep `security_id`; avoid CSV on poll |
| `_super_order` / invalid syntax | Python 3.10+ or `pip install 'dhanhq==2.0.2'` |
