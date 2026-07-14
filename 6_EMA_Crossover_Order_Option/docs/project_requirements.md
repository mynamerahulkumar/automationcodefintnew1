# GitHub Copilot Prompt – Build a Professional Dhan EMA Crossover Trading Engine

## Role

You are a senior Python quantitative developer, professional algo trader, and software architect.

Build a **production-ready Dhan EMA Crossover Trading Engine** that is lightweight, modular, fault-tolerant, and optimized for continuous 24×7 execution on both a local machine and a low-cost AWS VM (1 GB RAM).

The code should follow professional software engineering practices and be easy to extend with additional strategies in the future.

---

# Primary Goal

Build a Python FastAPI application that automatically trades **Dhan Stocks and Options** using an **EMA Crossover Strategy**.

The bot should:

* Run continuously
* Poll market data every configurable interval (default 30 seconds)
* Detect EMA crossover
* Place LIMIT BUY/SELL orders using Dhan API
* Maintain logs
* Be restart-safe
* Consume very little CPU and RAM

---

# Reference Files (Use as Source of Truth)

Do **not** rewrite the Dhan API implementation from scratch.

Use these existing project files as references:

```
Dhan_SRP.py
docs/project_requirements.md
security_id/api-scrip-master.csv
```

Reuse existing helper functions wherever possible.

---

# Technology Stack

Use only lightweight libraries.

Backend

* Python 3.12+
* FastAPI
* Uvicorn
* Requests
* Pandas (CSV loading only)
* PyYAML

Avoid

* Celery
* Redis
* RabbitMQ
* SQL databases
* Docker
* Kubernetes
* Heavy ML libraries
* Async frameworks unless absolutely required

The project must comfortably run on a **1 GB RAM AWS VM**.

---

# Project Structure

```
project/

app/
│
├── api.py
├── bot.py
├── strategy.py
├── order_service.py
├── dhan_client.py
├── config_loader.py
├── security_master.py
├── market_data.py
├── logger.py
├── scheduler.py
├── state.py
└── utils.py

config/
└── config.yaml

security_id/
└── api-scrip-master.csv

logs/
└── trading.log

Dhan_SRP.py
docs/
└── srp_dhan_helper.md

start.py
stop.py
logs.py

requirements.txt
README.md
```

---

# Configuration File

Create

```
config/config.yaml
```

Everything must be configurable.

Example

```yaml
broker:
  client_id: ""
  access_token: ""

trading:
  exchange: NSE
  segment: EQUITY
  stock_name: HDFCBANK
  security_id: ""
  quantity: 1
  order_type: LIMIT
  transaction_type: BUY
  limit_price: 0

strategy:
  name: EMA_CROSSOVER
  timeframe: 5m
  fast_ema: 9
  slow_ema: 21
  polling_seconds: 30

risk:
  target_percent: 2
  stoploss_percent: 1
  trailing_sl: false

bot:
  paper_trade: false
  one_position_only: true
  cooldown_seconds: 60
  log_level: INFO
```

Nothing should be hardcoded.

---

# Security Master

Load

```
security_id/api-scrip-master.csv
```

Only once during startup.

Automatically lookup

* Trading Symbol
* Security ID

using

```
stock_name
```

If security_id is already present in config, use it directly.

Otherwise automatically search the CSV.

Cache the result.

Never reload CSV on every poll.

---

# Trading Strategy

Implement

## EMA Crossover

Configurable

* Fast EMA
* Slow EMA
* Timeframe

Logic

BUY

Fast EMA crosses above Slow EMA

SELL

Fast EMA crosses below Slow EMA

Generate signals only on confirmed candle close.

Avoid duplicate signals.

Maintain last signal in memory.

---

# Order Execution

Support

* Stock
* Option

LIMIT orders only.

Order parameters

* BUY
* SELL
* Quantity
* Exchange
* Product
* Security ID
* Limit Price

Use Dhan API implementation from

```
Dhan_SRP.py
```

Do not create custom REST calls if helper methods already exist.

---

# TP / SL

Store only in configuration.

Do not implement exit management yet.

Keep placeholders so TP/SL can be added later.

---

# Polling Engine

When

```
python start.py
```

runs

The bot should

* Load configuration
* Validate configuration
* Load Security Master
* Print selected configuration
* Initialize Dhan
* Start FastAPI
* Start EMA polling

Default polling interval

```
30 seconds
```

Must be configurable in YAML.

---

# Startup Console

When start.py launches

Display

```
==================================
SRP Trading Engine
==================================

Mode              LIVE

Broker            DHAN

Strategy          EMA Crossover

Exchange          NSE

Segment           EQUITY

Stock             HDFCBANK

Security ID       1333

Fast EMA          9

Slow EMA          21

Timeframe         5m

Polling           30 sec

TP                2%

SL                1%

Status            RUNNING
==================================
```

Display clear startup information.

---

# Process Management

If

```
python start.py
```

is executed again

Automatically

* detect previous running instance
* gracefully stop previous bot
* release port 7001
* start new bot

Never allow two bots simultaneously.

Use PID file.

Example

```
run/bot.pid
```

---

# FastAPI

Run on

```
0.0.0.0

Port 7001
```

Endpoints

GET

```
/health
```

returns

```
Running
```

GET

```
/status
```

returns

* Bot status
* Strategy
* Symbol
* Current signal
* Last trade
* Poll interval

POST

```
/reload-config
```

Reload YAML.

POST

```
/place-order
```

Manual order.

---

# Logging

Write all logs

```
logs/trading.log
```

Include

Startup

Configuration

EMA values

Signals

Orders

Responses

Errors

Exceptions

Restart

Shutdown

---

# logs.py

Running

```
python logs.py
```

should continuously display

```
logs/trading.log
```

like

```
tail -f
```

---

# stop.py

Gracefully stop

* FastAPI
* Polling loop

Delete PID file.

Close HTTP sessions.

Flush logs.

---

# Error Handling

Handle

Invalid token

No internet

CSV missing

Invalid symbol

Invalid security id

API timeout

Rate limit

Empty candles

Duplicate signals

Invalid configuration

Port already used

Recover gracefully.

---

# Performance Requirements

This application will run on a **1 GB RAM AWS VM**.

Optimize aggressively.

Requirements

* RAM usage below ~150 MB while idle.
* Startup time under 3 seconds.
* Load CSV only once.
* Reuse HTTP sessions.
* Cache security IDs.
* Poll only once every configured interval.
* Avoid unnecessary object creation.
* Avoid DataFrame recreation inside polling.
* No busy waiting.
* Sleep efficiently.
* Minimal CPU usage.
* Support months of continuous execution without memory leaks.

---

# Code Quality

Professional architecture.

Use

* Type hints
* Docstrings
* Dependency separation
* Modular classes
* Single responsibility principle
* Reusable utilities
* Configuration-driven design
* Clean logging
* No duplicated code

---

# Future Extensibility

Design the project so future strategies can be added without changing the core engine.

Future strategies include:

* SMA Crossover
* RSI
* Supertrend
* Bollinger Bands
* MACD
* VWAP
* ORB (Opening Range Breakout)
* Multi-timeframe EMA
* Bank Nifty Options
* Nifty Options
* Trailing Stop Loss
* Paper Trading
* Backtesting
* Telegram Alerts
* Web Dashboard
* Multi-symbol scanning
* Multiple broker support

Each strategy should be pluggable by adding a new file under `app/strategy/` and selecting it in `config.yaml`.

---

# Deliverables

Generate a complete, production-ready project including:

* Modular FastAPI application
* EMA crossover engine
* Polling scheduler
* Configuration loader
* Security master loader
* Dhan client wrapper using `Dhan_SRP.py`
* Strategy module
* Order execution service
* PID-based process management
* Logging system
* `start.py`
* `stop.py`
* `logs.py`
* `requirements.txt`
* `README.md`

The implementation should prioritize reliability, low memory usage, maintainability, and continuous 24×7 operation on both a local machine and an AWS 1 GB RAM instance while keeping cloud costs as low as possible.
