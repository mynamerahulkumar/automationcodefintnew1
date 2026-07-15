# Setup Guide — Windows, macOS, and Linux

Step-by-step instructions to install and run the **SRP Dhan EMA Crossover Trading Engine** on your local machine.

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Python | **3.12 or newer** |
| Internet | Required for `pip install` and Dhan API calls |
| Dhan account | API access enabled with `client_id` and `access_token` |
| Disk space | ~500 MB (venv + dependencies + security master CSV) |

### Check Python version

**macOS / Linux**

```bash
python3 --version
```

**Windows (PowerShell or CMD)**

```powershell
python --version
```

If Python is not installed:

- **Windows:** Download from [python.org](https://www.python.org/downloads/) — check **"Add Python to PATH"** during install.
- **macOS:** `brew install python@3.12` or download from python.org.
- **Linux (Ubuntu/Debian):** `sudo apt update && sudo apt install python3 python3-venv python3-pip`

---

## 1. Get the Project

Open a terminal and navigate to the project folder.

**macOS / Linux**

```bash
cd /path/to/automationcodefintnew1/2_EMA_Crossover_Order_Stock
```

**Windows (PowerShell)**

```powershell
cd C:\path\to\automationcodefintnew1\2_EMA_Crossover_Order_Stock
```

---

## 2. Create a Virtual Environment

A virtual environment keeps project dependencies isolated from your system Python.

### macOS / Linux

```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal prompt.

### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If you get an execution policy error:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

### Windows (CMD)

```cmd
python -m venv venv
venv\Scripts\activate.bat
```

---

## 3. Install Dependencies

With the virtual environment activated on any OS:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Expected packages include: `fastapi`, `uvicorn`, `pyyaml`, `requests`, `dhanhq`, `pandas`, `numpy`, `pytz`, `mibian`.

### Verify installation

```bash
python -c "from app.config_loader import get_config_loader; print('OK')"
```

You should see `OK` with no errors.

---

## 4. Configure the Bot

### Credentials (`.env`) — required

Copy the template and add your Dhan credentials:

**macOS / Linux**

```bash
cp .env.example .env
```

**Windows (PowerShell / CMD)**

```powershell
copy .env.example .env
```

Edit `.env`:

```env
DHAN_CLIENT_ID=YOUR_CLIENT_ID
DHAN_ACCESS_TOKEN=YOUR_ACCESS_TOKEN
```

Do **not** put credentials in `config.yaml`. `.env` is gitignored and loaded automatically on startup.

You can still override with shell environment variables if needed — they take precedence over `.env` values already in the process.

### Trading settings (`config/config.yaml`)

```yaml
trading:
  exchange: NSE
  segment: EQUITY
  stock_name: HDFCBANK
  security_id: ""
  quantity: 1
  product_type: INTRADAY
  order_type: LIMIT
  transaction_type: BUY
  limit_price: 0

strategy:
  name: EMA_CROSSOVER
  timeframe: 5m
  fast_ema: 9
  slow_ema: 21
  polling_seconds: 30

bot:
  paper_trade: true    # start with true — no real orders sent
  one_position_only: true
  cooldown_seconds: 60
  log_level: INFO
  startup_poll_logs: 2 # polls shown on CLI at start, then detaches (0 = skip)
```

### Security ID lookup

`stock_name` (e.g. `HDFCBANK`) is automatically resolved to a `security_id` from:

```
security_id/api-scrip-master.csv
```

You can override with an explicit `security_id` in config if needed.

---

## 5. Run the Engine

Always activate the virtual environment first, then run from the project root.

### Start

**macOS / Linux / Windows**

```bash
python start.py
```

Expected output:

```
==================================
SRP Trading Engine
==================================

Mode              PAPER
...
Status            RUNNING
==================================
Started SRP Trading Engine on 0.0.0.0:7001 (PID xxxxx)
```

The bot runs on **port 7001**. Running `start.py` again automatically stops the previous instance.

`start.py` streams `logs/trading.log` to your terminal until the configured number of EMA polls complete (default **2**, set via `bot.startup_poll_logs`), then exits the CLI while the bot keeps running in the background.

```yaml
bot:
  startup_poll_logs: 2   # 0 = no CLI log stream, detach immediately
```

### View logs (separate terminal)

Activate venv in the new terminal, then:

```bash
python logs.py
```

Press `Ctrl+C` to exit the log viewer (the bot keeps running).

### Stop

```bash
python stop.py
```

---

## 6. Verify It Is Working

### Health check

**macOS / Linux**

```bash
curl http://127.0.0.1:7001/health
```

**Windows (PowerShell)**

```powershell
Invoke-RestMethod http://127.0.0.1:7001/health
```

Expected response: `Running`

### Bot status

**macOS / Linux**

```bash
curl http://127.0.0.1:7001/status
```

**Windows (PowerShell)**

```powershell
Invoke-RestMethod http://127.0.0.1:7001/status | ConvertTo-Json
```

**Browser (any OS)**

Open: [http://127.0.0.1:7001/status](http://127.0.0.1:7001/status)

### API docs (any OS)

Open: [http://127.0.0.1:7001/docs](http://127.0.0.1:7001/docs)

---

## 7. Going Live

Once paper trading looks correct in `logs/trading.log`:

1. Set `bot.paper_trade: false` in `config/config.yaml`
2. Restart the bot:

```bash
python stop.py
python start.py
```

Or hot-reload without restart:

```bash
curl -X POST http://127.0.0.1:7001/reload-config
```

**Before live trading:**

- Whitelist your machine's public IP in Dhan API settings (required on cloud/VPS).
- Confirm NSE market hours: Mon–Fri, 9:15 AM – 3:30 PM IST.
- Start with small `quantity`.

---

## 8. Daily Workflow

| Task | Command |
|------|---------|
| Start bot | `python start.py` |
| Watch logs | `python logs.py` |
| Check status | `curl http://127.0.0.1:7001/status` |
| Manual order | `curl -X POST http://127.0.0.1:7001/place-order` |
| Reload config | `curl -X POST http://127.0.0.1:7001/reload-config` |
| Stop bot | `python stop.py` |

On Windows PowerShell, replace `curl` with `Invoke-RestMethod` where needed.

---

## 9. Troubleshooting

### `ModuleNotFoundError: No module named 'yaml'` (or other packages)

Virtual environment is not activated, or dependencies were not installed.

```bash
source venv/bin/activate        # macOS/Linux
.\venv\Scripts\Activate.ps1     # Windows PowerShell
pip install -r requirements.txt
```

### `Broker credentials missing`

Create a `.env` file (copy from `.env.example`) and set `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`.

### `Security ID not found for stock: ...`

- Check `stock_name` spelling in `config/config.yaml` (e.g. `HDFCBANK`, not `HDFC BANK`).
- Confirm `security_id/api-scrip-master.csv` exists in the project folder.

### `No running bot found` when running `stop.py`

The bot is already stopped. Start it with `python start.py`.

### Port 7001 already in use

```bash
python stop.py
python start.py
```

If that fails, find and kill the process manually.

**macOS / Linux**

```bash
lsof -i :7001
kill <PID>
```

**Windows (PowerShell)**

```powershell
netstat -ano | findstr :7001
taskkill /PID <PID> /F
```

### Dhan API authentication failed

- Regenerate your access token in the Dhan developer portal.
- Tokens expire — update `access_token` and restart or reload config.

### `Invalid IP` or `DH-905` error

Your IP is not whitelisted in Dhan settings. Add your current public IP at [web.dhan.co](https://web.dhan.co).

### Windows: `python` not recognized

Reinstall Python with **"Add Python to PATH"** checked, or use the full path:

```powershell
C:\Users\<You>\AppData\Local\Programs\Python\Python312\python.exe start.py
```

### Logs show `Failed to fetch candle data`

- Market may be closed (NSE hours only).
- Check internet connection.
- Verify Dhan credentials are valid.

---

## 10. Running on a Cloud VM (Linux)

Same steps as macOS/Linux. Recommended for 24×7 operation:

```bash
git clone <your-repo-url>
cd 2_EMA_Crossover_Order_Stock
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN

# Paper trade first
python start.py
```

Keep the session alive with `screen` or `tmux`:

```bash
tmux new -s trading
python start.py
# Detach: Ctrl+B then D
# Reattach: tmux attach -t trading
```

### AWS 1 GB RAM — if server exits with `exit=1` or `Killed`

The first Dhan poll loads market data. On a 1 GB VM this can OOM. Fixes:

```bash
# 1) Add 2 GB swap (one-time)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab
free -h

# 2) Pull latest code (low-memory equity cache + better crash logs)
cd ~/automationcodefintnew1/2_EMA_Crossover_Order_Stock
git pull
source venv/bin/activate
pip install -r requirements.txt

# 3) Restart — on failure start.py prints the last lines of uvicorn.out
python stop.py
python start.py
tail -50 logs/uvicorn.out
```

Also whitelist the **EC2 public IP** in Dhan API settings.

---

## Quick Reference

```
Project root:  2_EMA_Crossover_Order_Stock/
Config file:   config/config.yaml
Env file:      .env
Log file:      logs/trading.log
PID file:      run/bot.pid
API port:      7001
Health URL:    http://127.0.0.1:7001/health
Status URL:    http://127.0.0.1:7001/status
```

For strategy details, API reference, and architecture, see [README.md](README.md) and [docs/project_requirements.md](docs/project_requirements.md).
