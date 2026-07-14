# Setup Guide — Windows & Mac/Linux

Step-by-step setup for the **Dhan Limit Order FastAPI** project on your local machine or cloud server.

---

## What You Are Setting Up

This project runs a small FastAPI service that:

- Reads order settings from `config/config.yaml`
- Resolves security IDs from `security_id/api-scrip-master.csv`
- Places **LIMIT** stock or option orders on Dhan via `Dhan_SRP.py`

Default API port: **7001**

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Python | **3.10+ required** (3.11 or 3.12 recommended). `dhanhq` 2.2 uses `match`/`case` and fails on 3.9 with `invalid syntax (_super_order.py, line 54)` |
| Dhan account | Client ID + access token from [web.dhan.co](https://web.dhan.co) → Profile → **DhanHQ Trading APIs** |
| Internet | Required for Dhan API and security master |
| Git | Optional, if cloning from GitHub |

### Dhan account requirements

- **Live orders:** your machine/server **public IP must be whitelisted** in Dhan API settings.
- **Market data / option chain:** active Dhan data plan may be required.
- **Market hours (NSE):** Mon–Fri, 9:15 AM – 3:30 PM IST for regular session orders.

### Platform notes

| Platform | Best for |
|----------|----------|
| **Mac / Linux** | Local dev and cloud deployment (recommended) |
| **Windows** | Local dev works; use PowerShell or Command Prompt. For production, prefer Linux VPS or WSL2 |

`stop.py` uses Unix signals (`SIGTERM`). On native Windows, graceful stop may be limited — see [Stop the server](#stop-the-server) below.

---

## 1. Get the Project

### Option A — Already on your machine

Open a terminal in the project folder:

```text
1_Place_Limit_Order_Stock/
```

### Option B — Clone from Git

**Mac / Linux / WSL / PowerShell:**

```bash
git clone <your-repo-url>
cd automationcodefintnew1/1_Place_Limit_Order_Stock
```

---

## 2. Install Python

### Mac

```bash
# Check version
python3 --version

# If missing, install via Homebrew
brew install python@3.12
```

### Linux (Ubuntu/Debian)

```bash
python3 --version

sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### Windows

1. Download Python from [python.org/downloads](https://www.python.org/downloads/)
2. Run the installer
3. **Check** “Add python.exe to PATH”
4. Verify in **PowerShell** or **Command Prompt**:

```powershell
python --version
```

---

## 3. Create Virtual Environment

Always use a virtual environment so dependencies stay isolated.

### Mac / Linux

```bash
cd 1_Place_Limit_Order_Stock

python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### Windows (PowerShell)

```powershell
cd 1_Place_Limit_Order_Stock

python -m venv venv
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

### Windows (Command Prompt)

```cmd
cd 1_Place_Limit_Order_Stock

python -m venv venv
venv\Scripts\activate.bat
```

---

## 4. Install Dependencies

With the virtual environment **activated**:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Installed packages include: `fastapi`, `uvicorn`, `pandas`, `pyyaml`, `requests`, `dhanhq`, `numpy`, `pytz`, `mibian`.

Verify:

```bash
python -c "import fastapi, dhanhq; print('OK')"
```

---

## 5. Security Master CSV

The app resolves stock/option `security_id` from:

```text
security_id/api-scrip-master.csv
```

This file should already exist in the repo. If missing, download Dhan’s scrip master and save it to that path, or let `Dhan_SRP.py` fetch it on first order (slower, needs network).

---

## 6. Configure Credentials & Trading

### Credentials — `.env` file (required)

```bash
cp .env.example .env
```

Edit `.env`:

```env
DHAN_CLIENT_ID=YOUR_CLIENT_ID
DHAN_ACCESS_TOKEN=YOUR_ACCESS_TOKEN
```

`.env` is gitignored. Do not commit real tokens.

You can still override the same variables in the shell if needed:

**Mac / Linux:**

```bash
export DHAN_CLIENT_ID="YOUR_CLIENT_ID"
export DHAN_ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
```

**Windows PowerShell:**

```powershell
$env:DHAN_CLIENT_ID="YOUR_CLIENT_ID"
$env:DHAN_ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
```

### Trading settings — `config/config.yaml`

### Example — equity (stock) order

```yaml
trading:
  segment: EQUITY
  exchange: NSE
  stock_name: HDFCBANK
  security_id: ""              # leave empty for auto lookup from CSV
  quantity: 1
  product_type: INTRADAY
  transaction_type: BUY
  order_type: LIMIT
  limit_price: 1890.50
  validity: DAY

risk:
  target_percent: 2
  stoploss_percent: 1
  trailing_sl: false

cloud:
  log_level: INFO
  dry_run: true                # true = no live order (safe for first test)
  console_log: true            # true on local machine
  auto_place_order: true       # false = start server only, no auto order
```

### Example — option order

Set `segment: OPTION` and fill option fields:

```yaml
trading:
  segment: OPTION
  exchange: NSE
  stock_name: NIFTY            # underlying
  expiry: "2026-07-30"
  strike: 25000
  option_type: CE              # CE or PE
  quantity: 75
  product_type: INTRADAY
  transaction_type: BUY
  order_type: LIMIT
  limit_price: 120.0
```

---

## 7. First Run (Safe Test)

1. Set `cloud.dry_run: true` in `config/config.yaml`
2. Activate venv (see step 3)
3. Start the server:

```bash
python start.py
```

`start.py` will:

- Print a startup summary (symbol, security ID, dry-run flag)
- Start FastAPI on `http://0.0.0.0:7001`
- Call `/place-order` automatically if `auto_place_order: true`

Expected dry-run output includes something like:

```text
Result:       DRY RUN ONLY (order NOT sent to Dhan)
```

---

## 8. API Usage

### Health check

**Mac / Linux:**

```bash
curl http://localhost:7001/health
```

**Windows PowerShell:**

```powershell
Invoke-RestMethod http://localhost:7001/health
```

Expected:

```json
{"status": "running"}
```

### Place order manually

**Mac / Linux:**

```bash
curl -X POST http://localhost:7001/place-order
```

**Windows PowerShell:**

```powershell
Invoke-RestMethod -Method POST http://localhost:7001/place-order
```

### Reload config (no restart)

**Mac / Linux:**

```bash
curl -X POST http://localhost:7001/reload-config
```

**Windows PowerShell:**

```powershell
Invoke-RestMethod -Method POST http://localhost:7001/reload-config
```

---

## 9. Logs & Server Control

### View logs

**Mac / Linux / Windows (with venv active):**

```bash
python logs.py
```

Press `Ctrl+C` to stop tailing.

Log file location: `logs/trading.log`

### Stop the server

**Mac / Linux:**

```bash
python stop.py
```

**Windows:**

- Preferred: run the project in **WSL2** and use `python stop.py`
- Native Windows: `stop.py` may not send signals correctly. Alternatives:
  - Close the terminal where the server runs
  - Or find and end the Python process in Task Manager
  - Or in PowerShell: `Get-Process python | Stop-Process` (stops all Python processes — use carefully)

---

## 10. Go Live (Real Orders)

Only after dry-run works:

1. Confirm your **public IP is whitelisted** in Dhan
2. Confirm **market is open** (for regular session)
3. Set correct `limit_price`, `quantity`, and symbol in `config/config.yaml`
4. Set:

```yaml
cloud:
  dry_run: false
```

5. Restart:

```bash
python stop.py    # Mac/Linux
python start.py
```

Or call `POST /place-order` while the server is already running.

---

## 11. Cloud / VPS (Mac/Linux server)

On a small Linux VPS (e.g. 1 GB RAM):

```yaml
cloud:
  dry_run: false
  console_log: false    # logs only to file
  auto_place_order: false
```

```bash
source venv/bin/activate
python start.py
python logs.py         # in another SSH session
```

Whitelist the **VPS public IP** in Dhan before live trading.

---

## 12. Troubleshooting

| Problem | What to check |
|---------|----------------|
| `invalid syntax (_super_order.py, line 54)` | Python is **older than 3.10**. Install Python 3.11+, recreate `venv`, reinstall deps (see below) |
| `python: command not found` | Use `python3` on Mac/Linux, or reinstall Python on Windows with PATH enabled |
| `No module named 'fastapi'` | Activate venv, then `pip install -r requirements.txt` |
| `Security ID not found for stock` | Check `stock_name` spelling; ensure `security_id/api-scrip-master.csv` exists |
| `Credentials not found` | Copy `.env.example` to `.env` and set `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` |
| `Invalid IP` / `DH-905` | Whitelist your public IP in Dhan API settings |
| Order fails outside market hours | Use AMO only if intended; otherwise trade during NSE session |
| Port 7001 already in use | Run `python stop.py` (Mac/Linux) or kill the old process |
| `auto_place_order` places when you only want the server | Set `cloud.auto_place_order: false` |

### EC2: fix `invalid syntax (_super_order.py)`

Amazon Linux often ships Python 3.9. Recreate the venv with 3.11+:

```bash
python3 --version   # if < 3.10, continue

# Amazon Linux 2023
sudo dnf install -y python3.11 python3.11-pip python3.11-devel

cd ~/automationcodefintnew1/1_Place_Limit_Order_Stock
deactivate 2>/dev/null || true
rm -rf venv
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python start.py
```

Confirm:

```bash
python --version   # must be 3.10+
python -c "from dhanhq import dhanhq; print('dhanhq OK')"
```

---

## 13. Using `Dhan_SRP.py` in Other Algo Repos

This folder also includes a portable broker module for custom algos:

| File | Purpose |
|------|---------|
| `Dhan_SRP.py` | Copy into other repos as broker layer |
| `srp_dhan_helper.md` | Full API reference and examples |

Typical pattern in another repo:

```python
from broker.Dhan_SRP import Dhansrp

dhan = Dhansrp(config_path="config/dhan_config.json")
result = dhan.place_stock_order(symbol="HDFCBANK", quantity=10, price=1800.0, dry_run=True)
```

See `srp_dhan_helper.md` for complete usage.

---

## Quick Reference

### Mac / Linux — full setup

```bash
cd 1_Place_Limit_Order_Stock
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN
# edit config/config.yaml (dry_run: true first)
python start.py
python logs.py          # optional, another terminal
python stop.py          # when done
```

### Windows — full setup (PowerShell)

```powershell
cd 1_Place_Limit_Order_Stock
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then edit DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN
# edit config/config.yaml (dry_run: true first)
python start.py
python logs.py
```

---

## Related Docs

- `README.md` — project overview and API summary
- `srp_dhan_helper.md` — `Dhan_SRP.py` reference for algo development
- `project_requirements.md` — original build specification
