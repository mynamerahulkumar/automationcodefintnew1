# GitHub Copilot Prompt – Dhan Long Straddle + Supertrend Confirmation Bot

---

## Role

Act as a **Senior Python Software Architect**, **Professional Quant Developer**, **Low Latency Algo Trader**, and **Production Backend Engineer**.

Build a **production-ready Dhan Options Trading Bot** using **Python + FastAPI**.

The project must be optimized for:

* AWS Lightsail 1GB RAM
* Ubuntu Server
* Local Windows/Mac
* Very low CPU usage
* Very low memory usage
* Long-running process
* Easy future strategy additions

No unnecessary frameworks.

Only use:

* Python
* FastAPI
* Dhan API
* pandas
* ta (or pandas-ta)
* uvicorn

No Celery.
No Redis.
No Kafka.
No Docker.
No database.

Everything should run from one lightweight Python process.

---

# Strategy

## Long Straddle + Supertrend Confirmation

### Entry

At configured market entry time (default 09:15)

Buy simultaneously

* ATM CE
* ATM PE

Only one straddle per day.

No duplicate entries.

---

### Confirmation

After entry

Keep checking Supertrend.

If

Supertrend = BUY

Then

* Exit PUT
* Hold CALL
* Trail CALL

---

If

Supertrend = SELL

Then

* Exit CALL
* Hold PUT
* Trail PUT

---

No re-entry.

No reverse entry.

Once one leg exits

Only trail remaining profitable leg.

---

Trailing Stop

Configurable

Example

```
trail_percent: 1.0
```

or

```
trail_points: 10
```

Both configurable.

---

# Project Structure

```
project/

start.py

stop.py

logs.py

requirements.txt

config/

    config.yaml

core/

    dhan_client.py

    order_manager.py

    position_manager.py

    instrument_lookup.py

    scheduler.py

    logger.py

    cli.py

strategy/

    long_straddle_supertrend.py

indicator/

    supertrend.py

security_id/

    api-scrip-master.csv

docs/

    srp_dhan_helper.md

reference/

    Dhan_SRP.py
```

Make code modular.

Easy to add

EMA Strategy

RSI Strategy

ORB Strategy

MACD Strategy

later.

---

# Configuration

Everything configurable.

Example

```yaml
broker:

  client_id:

  access_token:

exchange: NSE

segment: OPTION

symbol: NIFTY

security_id:

expiry: nearest

strike_selection:

    type: ATM

    offset: 0

entry:

    enabled: true

    time: "09:15"

polling:

    interval_seconds: 30

    show_last_polls: 3

    always_print_cli: true

indicator:

    supertrend:

        enabled: true

        length: 10

        multiplier: 3

risk:

    quantity: 75

    max_daily_trade: 1

    sl_percent: 20

    tp_percent: 40

trail:

    enabled: true

    percent: 1

logging:

    level: INFO

server:

    host: 0.0.0.0

    port: 7003
```

Everything configurable.

Nothing hardcoded.

---

# Security ID Lookup

Security ID should be optional.

If omitted

Automatically read

```
security_id/api-scrip-master.csv
```

Search by

* Exchange
* Segment
* Symbol
* Expiry
* Strike
* Option Type

Return correct Security ID.

Cache lookup.

Do not scan CSV every polling cycle.

Read once.

Store in memory.

---

# Reference Files

Use

```
reference/Dhan_SRP.py
```

as reference for

* login
* order placement
* position handling
* market price
* order status

Use

```
docs/srp_dhan_helper.md
```

for helper functions and Dhan implementation details.

Use only FastAPI-based Python implementation.

No unnecessary abstractions.

---

# Start Script

Running

```
python start.py
```

should

---

## Step 1

Kill previous running bot automatically.

Use PID file.

Example

```
run/bot.pid
```

If process exists

Terminate gracefully.

Start fresh.

---

## Step 2

Validate configuration.

Show

```
Configuration Loaded Successfully
```

---

## Step 3

Display selected configuration.

Example

```
Broker

Client ID

Exchange

Segment

Underlying

Expiry

Strike Selection

Quantity

SL

TP

Trailing

Polling Interval

Supertrend Length

Multiplier

Entry Time

Port

```

---

## Step 4

Start FastAPI server

Port

```
7003
```

---

## Step 5

Start polling.

---

# Polling

Every

```
30 seconds
```

(configurable)

Collect

Current

Underlying Price

ATM Strike

CE LTP

PE LTP

Current Supertrend

Remaining Position

Open Orders

PnL

Trailing SL

Position Status

Timestamp

---

# CLI Dashboard

Every polling cycle

Display

```
==================================================

LONG STRADDLE SUPERTREND BOT

==================================================

Time

09:30:00

Underlying

NIFTY

Spot

25142.30

ATM

25150

CALL

BUY

LTP

152.30

PUT

BUY

LTP

121.50

Supertrend

BUY

Remaining Position

CALL

Exited Position

PUT

Current Profit

1250

Trailing Stop

145.20

Polling Count

35

Next Poll

30 sec

==================================================
```

If

```
always_print_cli = true
```

Refresh every polling cycle.

Otherwise

Only keep

Last

3

polls.

Configurable.

---

# Order Rules

At

09:15

Buy

ATM CE

ATM PE

Verify

Order Filled.

Retry configurable.

No market order slippage issues.

Support

Limit Order (default)

Optional Market Order.

---

# Exit Rules

If

Supertrend BUY

Exit PUT

Keep CALL

Trail CALL

---

If

Supertrend SELL

Exit CALL

Keep PUT

Trail PUT

---

If TP reached

Exit.

If SL reached

Exit.

---

End trading after exit.

---

# Logs

Create

```
logs/
```

Daily log file.

Example

```
logs/2026-07-12.log
```

Log

Every poll

Every signal

Every API request

Every order

Every error

Every retry

Every exit

PnL

Execution time

Memory usage

---

# logs.py

Running

```
python logs.py
```

should

Tail latest log

Like

```
tail -f
```

with colors.

---

# stop.py

Running

```
python stop.py
```

should

Read PID

Terminate bot gracefully

Close FastAPI

Cancel polling

Remove PID

Display

```
Bot stopped successfully
```

---

# FastAPI APIs

Implement lightweight APIs:

```
GET /

Health

GET /status

Current bot status

GET /config

Current loaded configuration

GET /positions

Current positions

GET /orders

Today's orders

GET /pnl

PnL

GET /logs

Latest logs
```

---

# Error Handling

Automatically retry

Network timeout

API timeout

Temporary Dhan failure

CSV read failure

Invalid security id

Log everything.

Never crash.

---

# Performance Requirements

Must support

AWS Lightsail

1GB RAM

Target

RAM

<120MB

CPU Idle

<2%

Startup

<2 seconds

Polling latency

<300ms excluding network

CSV loaded once only.

No repeated DataFrame creation.

Reuse HTTP sessions.

Avoid unnecessary object allocations.

Use lightweight logging.

No background threads unless required.

---

# Coding Standards

* Python 3.12+
* Type hints everywhere
* Dataclasses where appropriate
* PEP 8 compliant
* Structured logging
* No duplicated code
* Small reusable modules
* Clear separation of concerns
* Fully configurable through `config.yaml`
* Easy to extend with additional strategies

---

# Deliverables

Generate a complete, production-ready project including:

1. Full folder structure.
2. `requirements.txt` with minimal dependencies.
3. `config/config.yaml`.
4. `start.py`, `stop.py`, and `logs.py`.
5. FastAPI application listening on **port 7003**.
6. `core/` modules for Dhan client, instrument lookup, order management, scheduler, logging, CLI, and position management.
7. `indicator/supertrend.py`.
8. `strategy/long_straddle_supertrend.py`.
9. CSV-based Security ID auto-lookup with in-memory caching.
10. Automatic PID management so rerunning `start.py` stops the previous instance.
11. Live CLI dashboard with configurable refresh behavior and polling interval.
12. Robust error handling, retry logic, graceful shutdown, and optimization for continuous execution on a **1 GB AWS VM** with minimal CPU, memory, and API usage.
