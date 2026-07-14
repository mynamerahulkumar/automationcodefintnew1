# GitHub Copilot Prompt: Build a Production-Ready Dhan Long Straddle ORB Algo Trading Bot

## Objective

Build a **production-ready, lightweight, modular, configuration-driven Python FastAPI application** implementing a **Long Straddle + Opening Range Breakout (ORB)** strategy using the **Dhan API**.

The application must be designed for:

* **AWS Lightsail / EC2 (1 GB RAM)**
* Local Windows/Linux/Mac execution
* Low CPU usage
* Low memory usage
* Production deployment
* Easy future strategy additions

Do **NOT** create unnecessary abstractions or over-engineered architecture. Keep the code simple, modular, and efficient.

Use **Python + FastAPI only**.

No frontend.

---

# References

Use the following files as implementation references.

```
Dhan_SRP.py
docs/srp_dhan_helper.md
security_id/api-scrip-master.csv
```

Reuse helper methods whenever possible.

Do not rewrite Dhan APIs if helper methods already exist.

---

# Strategy

## Strategy Name

Long Straddle ORB

---

# Trading Logic

## Entry Time

Default

```
09:15
```

Configurable.

---

## Entry

At entry time

Place simultaneously

```
BUY ATM CALL

BUY ATM PUT
```

Both orders should use

* Limit Order
* Configurable limit buffer

---

# Opening Range

Default

```
15 Minutes
```

Configurable.

During first 15 minutes calculate

```
ORB HIGH

ORB LOW
```

---

# Breakout Logic

If

```
Spot > ORB HIGH
```

Immediately

```
Exit PUT

Keep CALL

Enable CALL Trailing Stop
```

---

If

```
Spot < ORB LOW
```

Immediately

```
Exit CALL

Keep PUT

Enable PUT Trailing Stop
```

---

# Exit Conditions

Exit remaining position when

* Trailing SL hit
* Target hit
* Stop Loss hit
* Square-off time
* Manual stop

---

# Option Selection

Everything configurable.

```
option_selection:

    type: ATM

    strike_offset: 0
```

Support

```
ATM

ITM

OTM
```

Support configurable offsets

```
0

1

2

3
```

Example

```
ATM Offset 0

ATM

OTM Offset 1

1 strike OTM

OTM Offset 2

2 strike OTM

ITM Offset 1

1 strike ITM
```

Automatically calculate strike using current spot.

---

# Security ID Resolution

Configuration should support

```
security_id:
```

Security ID is optional.

If blank,

Automatically resolve security ID from

```
security_id/api-scrip-master.csv
```

using

* Underlying
* Expiry
* Strike
* Option Type

Never require user to manually enter security ID.

---

# Polling

No websocket.

Only polling.

Default

```
30 seconds
```

Configurable.

Sleep between polling cycles to minimize CPU usage.

---

# Configuration

Create

```
config/config.yaml
```

Everything must be configurable.

Nothing hardcoded.

Example

```yaml
server:

  host: 0.0.0.0

  port: 7003

bot:

  enabled: true

  polling_interval_seconds: 30

  always_refresh_cli: true

  cli_refresh_every: 3

strategy:

  name: Long Straddle ORB

  entry_time: "09:15"

  opening_range_minutes: 15

  square_off_time: "15:15"

trading:

  exchange: NSE

  underlying: NIFTY

  expiry: WEEKLY

  quantity: 75

option_selection:

  type: ATM

  strike_offset: 0

order:

  order_type: LIMIT

  limit_buffer: 0.50

risk:

  stop_loss_percent: 25

  take_profit_percent: 50

  trailing_enabled: true

  trailing_type: PERCENT

  trailing_percent: 10

security:

  symbol: NIFTY

  security_id:

logging:

  level: INFO

  console: true

  file: true

dhan:

  client_id:

  access_token:
```

---

# FastAPI

Run on

```
localhost:7003
```

Create endpoints

```
GET /

GET /health

GET /status

GET /config
```

No authentication required.

---

# Order Management

Support

* Place Order
* Modify Order
* Cancel Order
* Exit Position

Track separately

CALL

PUT

Store

* Order ID
* Entry Price
* Quantity
* Current Price
* Current PnL
* Stop Loss
* Target
* Trailing Stop
* Position Status

---

# CLI Dashboard

When

```
python start.py
```

runs

Display complete selected configuration.

Example

```
========================================================

SRP DHAN LONG STRADDLE ORB BOT

========================================================

Bot Status

RUNNING

Strategy

Long Straddle ORB

Underlying

NIFTY

Expiry

Weekly

Strike Type

ATM

Strike Offset

0

Entry Time

09:15

Opening Range

15 Minutes

Quantity

75

Order Type

LIMIT

Take Profit

50%

Stop Loss

25%

Trailing

Enabled

Polling

30 Seconds

FastAPI Port

7003

CSV Security Resolution

Enabled

========================================================

BOT STARTED SUCCESSFULLY

========================================================
```

---

# Every Poll

Display

Current Time

Spot Price

ATM Strike

CALL Strike

PUT Strike

CALL Security ID

PUT Security ID

CALL LTP

PUT LTP

CALL Entry

PUT Entry

CALL PnL

PUT PnL

Combined PnL

ORB High

ORB Low

Current Candle Open

Current Candle High

Current Candle Low

Current Candle Close

Breakout Status

Inside Range

Above High

Below Low

CALL Status

PUT Status

Trailing Stop

Target

Stop Loss

API Response Time

Next Poll

---

If

```
always_refresh_cli=true
```

Refresh every poll.

Otherwise

Refresh every

```
3 polls
```

Configurable.

---

# Logging

Store logs

```
logs/bot.log
```

Log

* Startup
* Configuration
* Every poll
* Every API request
* Every API response
* Orders
* Exits
* Errors
* Shutdown

Use rotating log files to avoid excessive disk usage.

---

# logs.py

Running

```
python logs.py
```

should

Live stream

```
logs/bot.log
```

similar to

```
tail -f
```

---

# start.py

Running

```
python start.py
```

must

* Load configuration
* Validate configuration
* Resolve Security IDs
* Print configuration
* Kill previous running instance automatically
* Start FastAPI
* Start polling
* Start scheduler
* Start CLI
* Start logging

Never allow two bot instances.

Use PID file.

---

# stop.py

Running

```
python stop.py
```

must

* Stop polling
* Stop FastAPI
* Release PID file
* Close Dhan session
* Flush logs
* Exit gracefully

Display

```
Bot stopped successfully.
```

---

# Performance Optimization (Very Important)

This bot will run on a **1 GB RAM AWS VM**, so optimize for minimal resource usage.

Requirements:

* Use synchronous code unless asynchronous execution is necessary.
* Avoid unnecessary threads and background workers.
* Do not use WebSockets.
* Poll only at the configured interval.
* Read `config.yaml` once at startup.
* Load `api-scrip-master.csv` once and cache it in memory.
* Reuse a single Dhan client/session throughout the bot's lifetime.
* Avoid repeated DataFrame creation; use efficient lookups.
* Keep memory usage under approximately **150 MB** during normal operation.
* Keep CPU usage near idle between polls by sleeping instead of busy-waiting.
* Minimize API calls by requesting only the data needed for the current strategy.
* Use efficient logging with rotating files.
* Avoid heavy dependencies and unnecessary frameworks.
* Design the code so multiple strategies can later share the same Dhan client, configuration loader, logger, and order manager.

---

# Code Quality

Follow

* PEP 8
* SOLID principles where practical
* Type hints
* Clear module separation
* Reusable utility functions
* Minimal dependencies
* No duplicated code
* Production-quality exception handling
* Configuration-driven design

---

# requirements.txt

Keep dependencies minimal.

Example:

```
fastapi
uvicorn
dhanhq
pandas
pyyaml
requests
python-dotenv
psutil
colorama
tabulate
pytz
```

Do not add unnecessary packages.

---

# Deliverables

Generate a complete production-ready project containing:

* Modular Python source code
* `config/config.yaml`
* `start.py`
* `stop.py`
* `logs.py`
* `requirements.txt`
* FastAPI server on **port 7003**
* Automatic Security ID resolution from `security_id/api-scrip-master.csv`
* Long Straddle ORB strategy
* Configurable ATM/ITM/OTM option selection with strike offsets
* Live CLI dashboard with all relevant trading and bot status values
* Structured rotating logs
* Single-instance execution using a PID file
* Optimized architecture for 1 GB RAM cloud deployment
* Clean, extensible codebase that can later support additional strategies such as Long Strangle, EMA, RSI, Supertrend, Bull Call Spread, Bear Put Spread, Iron Condor, and Iron Butterfly without major refactoring.
