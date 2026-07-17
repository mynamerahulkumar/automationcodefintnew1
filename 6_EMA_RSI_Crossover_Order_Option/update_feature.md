# Update Feature Guide — EMA/RSI Bot Fixes

Use this document to apply the same fixes we landed in `3_EMA_RSI_Trading_Stock` to other Dhan trading repos (low-RAM AWS, chart-aligned indicators, clearer CLI errors).

---

## 1. Align EMA / RSI with TradingView (or broker charts)

### Symptoms
- Bot LTP looks correct, but EMA 9 / EMA 21 / RSI differ a lot from the chart.
- Example: chart EMA9≈812, EMA21≈802, RSI≈54; bot on 5m showed both EMAs ~808 and RSI ~45.

### Root causes
| Issue | Effect |
|--------|--------|
| Wrong timeframe (e.g. bot `5m`, chart `1d`) | EMAs hug price on 5m; daily EMAs can diverge by ~10 pts |
| EMA seeded from first close | Diverges from TradingView (TV uses SMA of first N bars) |
| Too few bars in lookback | EMA/RSI never converge to chart |
| Daily history omits “today” | Yesterday’s close used → wrong indicators |
| Dhan daily `toDate` is **non-inclusive** | Requesting `toDate=today` returns only through yesterday |
| VM timezone UTC vs IST | “Today” candle sync uses wrong calendar date |

### Checklist
1. **Match chart timeframe in config**
   ```yaml
   strategy:
     timeframe: 1d   # or 5m / 15m — must match the chart you compare against
   ```
2. **Support daily in config loader** — return Dhan interval `"DAY"` for `1d` / `1day` (do not block day timeframes).
3. **EMA = TradingView-style SMA seed**
   - First `period` closes → SMA seed
   - Then standard EMA: `price * k + ema * (1 - k)` with `k = 2/(period+1)`
   - Pad early bars with NaN so series stays aligned with closes
4. **RSI = Wilder smoothing** (already typical); give enough history (≈200+ daily bars).
5. **Daily candle window**
   - `from_date = today_ist - ~400 days`
   - `to_date = today_ist + 1 day` (because Dhan daily `toDate` is non-inclusive)
6. **Sync today’s bar with LTP** when history still ends yesterday:
   - If last bar date &lt; IST today → append close/high/low = LTP
   - If last bar date == IST today → update close (and high/low) from LTP
7. **Always use Asia/Kolkata for “today”** on AWS (UTC VMs). Prefer `zoneinfo`; fallback to `pytz` on Python &lt; 3.9.

### Verify
```text
EMA9 / EMA21 / RSI14 should match the chart within ~0.01 on the same timeframe.
```

---

## 2. Run on AWS 1GB RAM without OOM / hang

### Symptoms
- Works on local Mac, fails or stalls on 1GB AWS.
- Generic: `Poll cycle failed — check logs`
- Or process killed / huge RSS when loading `api-scrip-master.csv` / `Dhan_SRP`.

### Root causes
- Loading ~200k-row instrument CSV into pandas (hundreds of MB)
- Importing full `Dhan_SRP` (pandas + mibian → scipy) on every poll
- Keeping large DataFrames in the poll hot path

### Checklist
1. **Always set `security_id` in config** and skip CSV when present:
   ```yaml
   market:
     trading_symbol: HDFCBANK
     security_id: "1333"
   ```
2. **Do not load `api-scrip-master.csv` into pandas on poll** if `security_id` is known.
3. **Market data path must not import `Dhan_SRP`**
   - Use a thin REST client (`requests` → `https://api.dhan.co/v2`) for:
     - `POST /charts/historical`
     - `POST /charts/intraday`
     - `POST /marketfeed/ltp`
   - Parse OHLC as plain lists (no pandas).
4. **Lazy-load heavy libs**
   - Import `Dhan_SRP` only when placing orders
   - Lazy-import `mibian` (pulls scipy) only for option Greeks helpers
5. **Modest lookback** (still enough for convergence)
   - Daily: ~200 bars (e.g. `max(slow*15, rsi*15, 200)`)
   - Intraday: ~120 bars
6. **`gc.collect()` after candle fetch** on small VMs.
7. **Cache LTP ~10–15s** and retry ticker 2–3 times with short backoff (Dhan rate-limits back-to-back LTP calls).

### Target memory
- Poll path (REST only): roughly **~50–60 MB** RSS vs **~130 MB+** with full `Dhan_SRP`.

---

## 3. Fix `dhanhq` on AWS: `invalid syntax (_super_order.py, line 54)`

### Symptoms
```text
Failed to fetch candles: invalid syntax (_super_order.py, line 54)
```

### Root cause
- `dhanhq` **2.2+** uses Python **`match` / `case`** (needs **Python 3.10+**).
- Many AWS images run **3.8 / 3.9** → import of `dhanhq` fails even before any API call.

### Checklist
1. **Never import `dhanhq` for candle/LTP polling** — use REST client instead (works on 3.9).
2. **Detect Python version at startup** and print it in the banner.
3. **Order placement**
   - Prefer **Python 3.10+** with `dhanhq>=2.2`, **or**
   - On older Python: `pip install 'dhanhq==2.0.2'` (no `match/case`).
4. On `SyntaxError` / `_super_order` failure, log a clear message:
   ```text
   dhanhq needs Python 3.10+ (match/case). Use REST for market data or upgrade Python / pin dhanhq==2.0.2
   ```

### REST auth headers (v2)
```http
access-token: <DHAN_ACCESS_TOKEN>
client-id: <DHAN_CLIENT_ID>
Content-type: application/json
Accept: application/json
```
Include `dhanClientId` in JSON body.

### LTP response shapes
Handle both SDK-wrapped and raw REST:
```json
{ "status": "success", "data": { "NSE_EQ": { "1333": { "last_price": 808.3 } } } }
```
and nested `data.data` variants — recursively find `last_price`.

---

## 4. Show real errors on `start.py` console

### Symptoms
```text
Waiting... Poll cycle failed — check logs/trading.log for details.
```
Actual cause (auth, OOM, SyntaxError, missing module) is buried in the log file.

### Checklist
1. Log poll failures as **one clear line** including exception type/message:
   ```text
   Unhandled error in poll cycle: MemoryError: ...
   Failed to fetch candles for HDFCBANK — Dhan API error: DH-901 ...
   ```
2. In the startup log tailer, parse `ERROR:` / `WARNING:` lines and print:
   ```text
   ERROR: <human-readable reason>
   ```
3. Map common cases:
   - `DH-901` → refresh `DHAN_ACCESS_TOKEN` in `.env`
   - `DH-902` → subscribe to Dhan Data APIs
   - `MemoryError` → keep `security_id`, don’t load CSV
   - `invalid syntax` / `_super_order` → Python 3.10+ or REST / pin `dhanhq==2.0.2`
   - `ModuleNotFoundError` → missing dependency name
4. If zero polls succeed, print final summary pointing to `logs/trading.log` and `logs/uvicorn.out`.

---

## 5. Files / modules pattern to copy

| Module | Role |
|--------|------|
| `core/dhan_rest.py` | Pure `requests` client: historical, intraday, LTP, epoch→IST |
| `core/dhan_client.py` | `get_dhanhq_lite()` → REST; `get_dhan_client()` → Dhan_SRP only for orders |
| `core/market_data.py` | Candles + LTP via lite client; daily sync; IST today; no pandas |
| `core/strategy.py` | SMA-seeded EMA + Wilder RSI |
| `core/config_loader.py` | `get_dhan_timeframe()` → `"5"` / `"DAY"`; allow `1d` |
| `start.py` | Banner Python version; surface real poll errors |

### Config reminders
```yaml
market:
  security_id: "1333"   # required on 1GB VMs
strategy:
  timeframe: 1d         # match your chart
polling:
  seconds: 30
  startup_poll_logs: 3
```

---

## 5b. `.env` — `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`

Credentials must live in **`.env`** (not `config.yaml`). Every repo using this stack should ship `.env.example` and load vars the same way.

### Create `.env` on each machine (local + AWS)

```bash
cp .env.example .env
# then edit .env with real values
```

### Required variables

| Variable | What it is | Where to get it |
|----------|------------|-----------------|
| `DHAN_CLIENT_ID` | Dhan client / user id | Dhan web → profile / API section |
| `DHAN_ACCESS_TOKEN` | JWT access token (expires) | Dhan web → generate access token |

### `.env` file format

```env
# Copy from .env.example. Do not commit .env (gitignored).

DHAN_CLIENT_ID=YOUR_CLIENT_ID
DHAN_ACCESS_TOKEN=YOUR_ACCESS_TOKEN
```

Example shape (use your real values; never paste tokens into git/docs):

```env
DHAN_CLIENT_ID=1234567890
DHAN_ACCESS_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### `.env.example` (safe to commit)

```env
# Copy this file to .env and fill in your Dhan credentials.
# Do not commit .env (it is gitignored).

DHAN_CLIENT_ID=YOUR_CLIENT_ID
DHAN_ACCESS_TOKEN=YOUR_ACCESS_TOKEN
```

### App loading rules (port to other repos)

1. Load with `python-dotenv` from project-root `.env` (e.g. `load_dotenv(".env")`).
2. Read only from environment:
   - `os.environ["DHAN_CLIENT_ID"]`
   - `os.environ["DHAN_ACCESS_TOKEN"]`
3. **Do not** put tokens in `config.yaml`, code, or `update_feature.md`.
4. On missing values, fail fast with a clear error:
   ```text
   Broker credentials missing. Set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in .env
   ```
5. REST market-data headers must use the same vars:
   ```http
   access-token: <DHAN_ACCESS_TOKEN>
   client-id: <DHAN_CLIENT_ID>
   ```
6. After changing `.env`, restart the bot (`python stop.py && python start.py`) so the process picks up new values.

### AWS / other servers

1. Create `.env` on the VM (same two keys) — do not rely on local Mac `.env`.
2. `chmod 600 .env` so only your user can read it.
3. Ensure `.env` is in `.gitignore`.
4. When token expires, update **only** `DHAN_ACCESS_TOKEN`, then restart.
5. Console error **DH-901** / `Invalid Authentication` → refresh `DHAN_ACCESS_TOKEN` in `.env`.

### Checklist when fixing another repo

- [ ] `.env.example` exists with `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`
- [ ] `.env` is gitignored and present on local + AWS
- [ ] Config loader / REST client reads both vars from environment
- [ ] No hardcoded client id or token in YAML/Python
- [ ] Restart after any `.env` change

---

## 6. Deploy checklist (other repo / AWS)

1. Copy `.env.example` → `.env` and set `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN`.
2. Copy REST market-data pattern (do not import `dhanhq` on poll).
3. Ensure `security_id` is set; skip instrument CSV on small VMs.
4. Align timeframe + EMA SMA seed + daily `toDate+1` + IST today + LTP sync.
5. Improve poll error logging so `start.py` shows the real failure.
6. On AWS run `python3 --version`:
   - **&lt; 3.10**: polling OK via REST; for orders upgrade Python or pin `dhanhq==2.0.2`
   - **≥ 3.10**: full stack OK with current `dhanhq`
7. Restart: `python stop.py && python start.py`
8. Confirm first polls show LTP / EMA / RSI (not generic “check logs”).
9. If auth fails: refresh `DHAN_ACCESS_TOKEN` in `.env` and restart.
---

## 7. Quick regression tests

After porting to another repo:

```bash
# Indicators match chart (same timeframe)
python -c "from core.market_data import MarketDataService; ..."

# dhanhq must NOT load during candle fetch
# sys.modules should not require 'dhanhq' for polls

# Forced error messaging
# Kill token → start.py should print DH-901, not a vague poll failure
```

---

## Summary

| Problem | Fix |
|---------|-----|
| Indicators ≠ chart | Same timeframe; SMA-seed EMA; long lookback; daily `toDate+1`; IST today + LTP bar |
| Fails on 1GB AWS | `security_id`; no CSV; REST polls; lazy Dhan_SRP/mibian |
| `invalid syntax (_super_order.py)` | Don’t import dhanhq 2.2 on Python &lt;3.10; use REST for data |
| Vague CLI errors | Log exception detail; map DH-901/902/OOM/syntax in `start.py` |
| Auth / DH-901 | Set `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` in `.env`; refresh token; restart |
