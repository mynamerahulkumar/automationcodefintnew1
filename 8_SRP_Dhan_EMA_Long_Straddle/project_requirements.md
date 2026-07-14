# Copilot Prompt — Dhan Long Straddle + EMA 9/21 Confirmation Trading Bot (Production Ready)

```text
Act as a Senior Python Software Architect, Professional Quant Developer, Low Latency Algo Trader, and Dhan API Expert.

Build a production-ready, lightweight, modular, cloud-optimized algorithmic trading bot for Dhan Broker using Python and FastAPI.

The project must be optimized for:

- AWS Lightsail / EC2
- 1 GB RAM
- Single CPU
- Ubuntu
- Local Windows/Mac/Linux
- Low API usage
- Low memory footprint
- Easy future strategy additions

The architecture should be clean and extensible.

==================================================
REFERENCE FILES
==================================================

Use these files as implementation references.

Reference Trading Code

Dhan_SRP.py

Reference Documentation

docs/srp_dhan_helper.md

Security Master

security_id/api-scrip-master.csv

Use FastAPI only.

No Streamlit.

No Django.

No Flask.

==================================================
STRATEGY
==================================================

Strategy Name

Long Straddle EMA Confirmation

Purpose

Capture volatility while using EMA crossover as trend confirmation.

==================================================
ENTRY
==================================================

When market opens (or configurable entry time)

Buy

• 1 ATM CE
• 1 ATM PE

at the same time.

Use configurable quantity.

Support

NIFTY
BANKNIFTY
FINNIFTY
MIDCPNIFTY
Sensex
Stocks

==================================================
EMA CONFIRMATION
==================================================

Use EMA

Fast EMA = 9

Slow EMA = 21

Configurable.

Once both positions are open

Continuously monitor EMA.

Bullish Confirmation

EMA9 crosses above EMA21

Immediately

Exit Put

Continue holding Call

Bearish Confirmation

EMA9 crosses below EMA21

Immediately

Exit Call

Continue holding Put

Only one side should remain after confirmation.

==================================================
EXIT RULES
==================================================

Remaining leg should support

Percentage Stop Loss

Percentage Target

Trailing Stop

Time Exit

Market Close Exit

Emergency Exit

Everything configurable.

==================================================
CONFIG FILE
==================================================

Create one config.yaml

Everything should be configurable.

Example

broker:

    client_id:

    access_token:

trading:

    exchange: NSE

    instrument: OPTION

    symbol: NIFTY

    expiry:

    strike_selection: ATM

    quantity: 75

security:

    security_id:

    security_lookup_from_csv: true

strategy:

    name: Long Straddle EMA Confirmation

ema:

    enabled: true

    fast: 9

    slow: 21

entry:

    entry_time: "09:20"

risk:

    target_percent: 20

    stoploss_percent: 10

    trailing_stop: true

    trailing_percent: 5

exit:

    market_close_exit: true

    exit_time: "15:20"

polling:

    interval_seconds: 30

    cli_refresh: true

    cli_history: 3

logging:

    level: INFO

    save_file: true

server:

    host: 0.0.0.0

    port:7003

==================================================
SECURITY ID
==================================================

Security ID should be optional.

If user provides

security_id

Use it directly.

Otherwise

Automatically search

security_id/api-scrip-master.csv

using

Exchange

Instrument

Expiry

Strike

Option Type

Symbol

No manual editing required.

==================================================
PROJECT STRUCTURE
==================================================

project/

    start.py

    stop.py

    logs.py

    config.yaml

    requirements.txt

    strategy/

        long_straddle_ema.py

    broker/

        dhan_api.py

    services/

        ema.py

        security_lookup.py

        order_manager.py

        logger.py

        polling.py

        process_manager.py

    logs/

    security_id/

        api-scrip-master.csv

==================================================
START.PY
==================================================

Running

python start.py

should

Load configuration

Validate configuration

Print configuration summary

Check if previous bot is already running

If running

Stop previous process

Start new process

Automatically

No manual intervention.

Display

=====================================

SRP Trading Bot

Strategy

Long Straddle EMA Confirmation

=====================================

Broker

Client

Exchange

Symbol

Expiry

Quantity

ATM

EMA

Polling Interval

Risk

Target

SL

Trailing

Log File

Server Port

7003

=====================================

Bot Started Successfully

=====================================

==================================================
PROCESS MANAGEMENT
==================================================

Only one instance should run.

If user executes

python start.py

again

Old process

Must terminate

New process starts.

Store PID.

Automatically clean stale PID.

==================================================
STOP.PY
==================================================

Running

python stop.py

Should

Find running process

Terminate gracefully

Cancel pending polling

Close API session

Clear PID

Print

Bot stopped successfully

==================================================
FASTAPI
==================================================

Run on

0.0.0.0

Port

7003

Provide endpoints

GET /

Health

GET /status

Current strategy

Current EMA

Current positions

PnL

Poll count

GET /config

GET /logs

POST /stop

==================================================
POLLING
==================================================

Default

30 seconds

Configurable.

Very lightweight.

No busy waiting.

No unnecessary API calls.

Use sleep.

==================================================
CLI DASHBOARD
==================================================

When bot starts

Continuously display information.

Do not print random logs.

Refresh dashboard.

Show minimum last

3 polling cycles

Configurable.

Display

Current Time

Current Poll

Current Price

EMA 9

EMA 21

EMA Trend

Current Position

ATM Strike

CE Status

PE Status

Entry Price CE

Entry Price PE

Current CE LTP

Current PE LTP

Remaining Leg

Current MTM

Target

Stoploss

Polling Interval

API Status

Server Status

Memory Usage

CPU Usage

Next Poll Countdown

If cli_refresh=true

Dashboard should continuously refresh.

Otherwise

Append logs.

==================================================
LOGGING
==================================================

Create

logs.py

Running

python logs.py

should continuously tail latest logs.

Log

Order Placement

EMA Signal

API Response

Errors

SL Hit

Target Hit

Exit

Market Close

Bot Start

Bot Stop

CSV Lookup

Polling

Log rotation

5 MB

Keep

5 files

==================================================
EMA ENGINE
==================================================

Create reusable EMA module.

Should return

EMA9

EMA21

Bullish

Bearish

Neutral

Cross detected

Previous crossover

Reusable by future strategies.

==================================================
ORDER MANAGER
==================================================

Centralized order manager.

Functions

Buy CE

Buy PE

Exit CE

Exit PE

Square Off All

Modify SL

Trail SL

Check Position

Retry failed order

Order validation

==================================================
ERROR HANDLING
==================================================

Retry

3 times

API timeout

Reconnect automatically

Graceful shutdown

Never crash because of

one failed API call.

==================================================
PERFORMANCE
==================================================

Must be optimized for

1 GB RAM

Memory target

Below 150 MB

CPU usage

Very low

No pandas unless absolutely necessary.

Prefer

csv

dataclasses

typing

pathlib

logging

httpx

asyncio

FastAPI

Use requests only if existing Dhan helper requires it.

Avoid unnecessary threads.

Avoid unnecessary background workers.

Avoid unnecessary dependencies.

==================================================
REQUIREMENTS.TXT
==================================================

Only minimal dependencies.

Example

fastapi

uvicorn

httpx

PyYAML

psutil

python-dotenv

pydantic

No heavy libraries.

==================================================
CODE QUALITY
==================================================

Use

Type hints

Dataclasses

Enums

SOLID principles

Repository pattern

Service layer

Dependency Injection where useful

Reusable utilities

No duplicated code.

No hardcoded values.

Everything configurable.

==================================================
FUTURE READY
==================================================

Architecture should allow adding strategies like

EMA Crossover

RSI

Supertrend

ORB

CPR

VWAP

MACD

Long Straddle Breakout

Long Strangle

Iron Fly

Iron Condor

without modifying the existing framework.

Each strategy should simply be added under

strategy/

and selected from config.yaml.

==================================================
DELIVERABLE
==================================================

Generate complete production-ready code with:

- Fully working project structure
- Modular Python implementation
- FastAPI server on port 7003
- start.py
- stop.py
- logs.py
- config.yaml
- requirements.txt
- CSV-based Security ID lookup
- PID-based process management
- Live CLI dashboard
- EMA calculation service
- Long Straddle EMA Confirmation strategy
- Centralized order manager
- Optimized logging
- Cloud-ready deployment
- Low RAM / Low CPU implementation suitable for a 1 GB AWS VM and local execution.
```
