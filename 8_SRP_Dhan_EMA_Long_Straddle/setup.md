# Setup — Long Straddle EMA Confirmation

## 1. Environment

```bash
cd 8_SRP_Dhan_EMA_Long_Straddle
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Credentials

Set in `config/config.yaml`:

```yaml
dhan:
  client_id: "YOUR_CLIENT_ID"
  access_token: "YOUR_ACCESS_TOKEN"
```

Or export:

```bash
export DHAN_CLIENT_ID=...
export DHAN_ACCESS_TOKEN=...
```

## 3. Paper vs live

Default config uses `bot.paper_trade: true`. Set to `false` only after static IP whitelisting and a successful paper dry-run.

## 4. Run

```bash
python start.py
```

Stop with `python stop.py`. Tail logs with `python logs.py`.

API: `http://127.0.0.1:7003/status`
