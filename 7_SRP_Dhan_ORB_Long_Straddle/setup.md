# Setup — SRP Dhan Long Straddle ORB Bot

## Requirements

- Python 3.10+ recommended (3.9+ minimum)
- Dhan API credentials (client id + access token)
- Static IP whitelisted on Dhan for order APIs
- Active Dhan data plan for LTP / intraday candles / option chain

## Install (macOS / Linux)

```bash
cd 7_SRP_Dhan_ORB_Long_Straddle
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Install (Windows)

```bat
cd 7_SRP_Dhan_ORB_Long_Straddle
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Configure

1. Edit `config/config.yaml`
2. Set credentials:

```yaml
dhan:
  client_id: "YOUR_CLIENT_ID"
  access_token: "YOUR_ACCESS_TOKEN"
```

Or export environment variables (preferred for servers):

```bash
export DHAN_CLIENT_ID="YOUR_CLIENT_ID"
export DHAN_ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
```

3. Review strategy / risk:

```yaml
trading:
  underlying: NIFTY
  expiry: WEEKLY
  quantity: 75

bot:
  paper_trade: true    # start in paper mode first
  polling_interval_seconds: 30
```

4. Ensure `security_id/api-scrip-master.csv` is present (already included).

## Run

```bash
python start.py
```

- Starts FastAPI on `0.0.0.0:7003`
- Kills any previous instance using `run/bot.pid`
- Prints the full configuration banner
- Streams a few live poll dashboards, then leaves the bot running

```bash
python logs.py      # live tail of logs/bot.log
python stop.py      # square-off open legs + stop process
```

## Verify

```bash
curl http://127.0.0.1:7003/health
curl http://127.0.0.1:7003/status
curl http://127.0.0.1:7003/config
```

## AWS Lightsail / EC2 (1 GB)

1. Install Python + venv as above
2. Prefer env vars for credentials
3. Run under `tmux` / `screen` or a systemd service:

```ini
[Unit]
Description=SRP Long Straddle ORB Bot
After=network.target

[Service]
WorkingDirectory=/path/to/7_SRP_Dhan_ORB_Long_Straddle
ExecStart=/path/to/venv/bin/python start.py
Restart=on-failure
Environment=DHAN_CLIENT_ID=...
Environment=DHAN_ACCESS_TOKEN=...

[Install]
WantedBy=multi-user.target
```

Keep `bot.paper_trade: true` until you confirm strike selection, ORB levels, and exits on a market day.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Credentials missing | Set `dhan.*` or `DHAN_*` env vars |
| Option not found | Refresh `api-scrip-master.csv`; check expiry / strike |
| Port in use | `python stop.py` then restart |
| Empty LTP / candles | Confirm Dhan data plan and market hours |
| Duplicate bots | `start.py` auto-kills prior PID; check `run/bot.pid` |
