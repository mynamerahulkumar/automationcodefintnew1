Act as a Senior Python Software Architect, Professional Quant Developer, and Low Latency Algo Trader.

Build a production-ready Python trading bot for DQUAN Cloud Trading API (Dhan) which trades NSE Stocks and Options using configurable strategies.

The project must be lightweight, optimized for AWS Lightsail/EC2 (1 GB RAM), Raspberry Pi, and local machine.

DO NOT over-engineer.
DO NOT use unnecessary frameworks.
Focus on speed, maintainability and reliability.

==========================================================
PROJECT GOAL
==========================================================

Create a configurable Dhan Trading Bot supporting:

1. EMA Strategy only
2. RSI Strategy only
3. EMA + RSI Strategy

User should be able to enable any strategy from config file.

Bot places LIMIT orders only.

Everything must be configurable.

Reference implementation:

- Dhan_SRP.py
- docs/srp_dhan_helper.md

Reuse helper methods wherever possible.

Only use Python + FastAPI.

No database.

No Redis.

No Celery.

No Docker.

No Kafka.

No unnecessary dependencies.

Must work both locally and on AWS 1GB VM.

==========================================================
PROJECT STRUCTURE
==========================================================

project/

    start.py
    stop.py
    logs.py

    config/

        config.yaml

    security_id/

        api-scrip-master.csv

    core/

        dhan_client.py
        signal_engine.py
        strategy.py
        order_manager.py
        market_data.py
        config_loader.py
        logger.py
        process_manager.py

    api/

        server.py

    logs/

        trading.log

    requirements.txt

==========================================================
FASTAPI
==========================================================

FastAPI runs on

Port

7003

API Endpoints

GET /

GET /status

GET /config

GET /logs

POST /start

POST /stop

GET /health

==========================================================
START.PY
==========================================================

Running

python start.py

should

1.
Check if bot already running

If yes

Kill previous process automatically.

Then

Start new process.

2.

Load config.

Print entire selected configuration.

Like

==================================================
SRP DHAN TRADING BOT
==================================================

Broker           : DHAN

Strategy         : EMA + RSI

Exchange         : NSE

Instrument       : STOCK

Trading Symbol   : HDFCBANK

Security ID      : 1333

Timeframe        : 5m

Fast EMA         : 9

Slow EMA         : 21

RSI Period       : 14

RSI Buy          : 60

RSI Sell         : 40

Quantity         : 10

Order Type       : LIMIT

Take Profit      : 1%

Stop Loss        : 0.5%

Polling          : 30 Seconds

==================================================

Bot Started Successfully...

==========================================================

STOP.PY
==========================================================

Kills running process safely.

Print

Bot stopped successfully.

==========================================================
LOGS.PY
==========================================================

Running

python logs.py

should display

Live logs

similar to

tail -f

==========================================================
CONFIG.YAML
==========================================================

Everything configurable.

Example

broker:

    client_id:
    access_token:

market:

    exchange: NSE

    instrument: STOCK

    trading_symbol: HDFCBANK

    security_id:

    expiry:

    strike:

    option_type:

strategy:

    mode:

        EMA

        RSI

        EMA_RSI

    timeframe: 5m

polling:

    seconds: 30

ema:

    enabled: true

    fast: 9

    slow: 21

rsi:

    enabled: true

    period: 14

    buy: 60

    sell: 40

trade:

    quantity: 10

    order_type: LIMIT

    product_type: CNC

    transaction_type: BUY

risk:

    take_profit_percent: 1

    stop_loss_percent: 0.5

logging:

    level: INFO

==========================================================
SECURITY ID
==========================================================

Security ID is OPTIONAL.

If empty

Automatically read

security_id/api-scrip-master.csv

Find matching

Trading Symbol

Populate Security ID automatically.

If Security ID exists

Use it directly.

==========================================================
SUPPORTED STRATEGIES
==========================================================

1)

EMA ONLY

Buy

Fast EMA crosses above Slow EMA

Sell

Fast EMA crosses below Slow EMA

------------------------

2)

RSI ONLY

Buy

RSI crosses above Buy Level

Sell

RSI crosses below Sell Level

------------------------

3)

EMA + RSI

BUY

Fast EMA > Slow EMA

AND

RSI > Buy Level

SELL

Fast EMA < Slow EMA

AND

RSI < Sell Level

==========================================================
EMA DEFINITIONS
==========================================================

Explain inside code comments.

Fast EMA

Smaller EMA

Examples

5

8

9

10

13

Responds faster.

Slow EMA

Higher EMA

Examples

20

21

34

50

100

200

Responds slower.

Recommended defaults

Fast EMA

9

Slow EMA

21

==========================================================
RSI DEFINITIONS
==========================================================

Period

14

Default.

Buy Level

60

Sell Level

40

Aggressive

Buy

55

Sell

45

Conservative

Buy

65

Sell

35

==========================================================
MARKET DATA
==========================================================

Every polling cycle

Fetch latest candle.

Calculate

Current Price

Fast EMA

Slow EMA

RSI

==========================================================
CLI OUTPUT
==========================================================

Every polling cycle display

-------------------------------------------------------

Time

Trading Symbol

Current Price

EMA Fast

EMA Slow

RSI

Signal

Trade Status

Open Position

PnL

-------------------------------------------------------

Example

22:15:31

HDFCBANK

Price

1934.45

EMA 9

1932.11

EMA 21

1930.90

RSI

61.32

Signal

BUY

Trade

Waiting

-------------------------------------------------------

Colorize output

BUY

Green

SELL

Red

NO SIGNAL

Yellow

==========================================================
ORDER EXECUTION
==========================================================

Only LIMIT Orders.

Configurable buffer.

Example

BUY

Current Price

100

Limit Price

100.10

SELL

Current Price

100

Limit Price

99.90

Buffer configurable.

==========================================================
POSITION MANAGEMENT
==========================================================

One position at a time.

No duplicate entries.

Track

Entry Price

Current Price

PnL

Take Profit

Stop Loss

Exit when TP or SL hits.

==========================================================
LOGGING
==========================================================

Log everything.

Startup

Configuration

Signals

EMA

RSI

Price

Orders

Errors

PnL

Shutdown

Write into

logs/trading.log

==========================================================
ERROR HANDLING
==========================================================

Retry API failures.

Handle

Internet disconnect

Invalid Security ID

Market Closed

Invalid Order

API timeout

Gracefully.

==========================================================
PERFORMANCE
==========================================================

Designed for

1GB RAM

Use

requests

Avoid pandas where possible during polling.

Load CSV only once.

Reuse Dhan client.

No memory leaks.

No unnecessary threads.

No busy loops.

Polling only.

Default

30 seconds.

Configurable.

==========================================================
DEPENDENCIES
==========================================================

Keep requirements minimal.

fastapi

uvicorn

requests

PyYAML

pandas (only for initial CSV loading)

numpy

ta

colorama

psutil

No heavy ML libraries.

==========================================================
CODE QUALITY
==========================================================

Type hints.

Dataclasses where useful.

SOLID principles.

Readable.

Production-ready.

Modular.

PEP8 compliant.

Extensive comments.

==========================================================
FINAL DELIVERABLE
==========================================================

Generate complete production-ready project including:

✔ start.py

✔ stop.py

✔ logs.py

✔ config.yaml

✔ FastAPI server

✔ Dhan integration

✔ EMA strategy

✔ RSI strategy

✔ EMA + RSI strategy

✔ Security ID auto lookup

✔ Process management

✔ Live CLI dashboard

✔ Logging

✔ Order execution

✔ Risk management

✔ requirements.txt

The generated code should be immediately runnable with minimal configuration changes and optimized for continuous 24×7 execution on an AWS 1 GB RAM VM with very low CPU and memory usage.