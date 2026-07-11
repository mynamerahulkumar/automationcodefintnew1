# STARTUP, PROCESS MANAGEMENT & RUNTIME REQUIREMENTS

## Bot Startup

When the user runs:

```bash
python start.py
```

the application must automatically perform the following steps:

### Step 1 — Process Management

* Check whether another instance of the trading bot is already running.
* If an existing bot process is found:

  * Gracefully stop the previous process.
  * Release all resources.
  * Close API connections.
  * Display:

```
Existing bot instance detected.

Stopping previous instance...

Previous instance stopped successfully.

Starting new instance...
```

* Only one bot instance may run at any time.
* Prevent duplicate polling loops or duplicate order execution.

---

## Step 2 — Load Configuration

Load `config/config.yaml`.

Validate every required configuration.

If any required configuration is missing, display a clear validation error and exit.

Automatically resolve the Security ID from `security_id/api-scrip-master.csv` if it is not configured.

---

## Step 3 — Display Complete Configuration

Before the trading engine starts, print the complete active configuration in a professional CLI dashboard.

Example:

```
============================================================
                 SRP DHAN TRADING BOT
============================================================

Broker              : DHAN

Strategy            : MACD + RSI

Exchange            : NSE

Instrument          : STOCK

Trading Symbol      : HDFCBANK

Security ID         : 1333

Timeframe           : 5m

Polling Interval    : 30 Seconds

MACD Fast EMA       : 12

MACD Slow EMA       : 26

MACD Signal EMA     : 9

RSI Period          : 14

RSI Buy Level       : 60

RSI Sell Level      : 40

Quantity            : 10

Order Type          : LIMIT

Product Type        : CNC

Limit Buffer        : 0.10

Take Profit         : 1%

Stop Loss           : 0.5%

Logging             : INFO

============================================================

Configuration Loaded Successfully.

Trading Engine Started Successfully.

Polling Market Every 30 Seconds...
```

---

# Runtime Behaviour

After startup the bot must immediately enter a continuous polling loop.

The polling interval must be configurable.

Example:

```yaml
polling:

    seconds: 30
```

Changing the configuration should be enough to change the polling frequency.

No code modifications should be required.

---

# Polling Loop

The bot must continuously execute the following workflow:

1. Fetch latest candle data from Dhan.
2. Calculate all required indicators.
3. Generate trading signal.
4. Check open positions.
5. Evaluate Stop Loss and Take Profit.
6. Place Limit Order if conditions are satisfied.
7. Update logs.
8. Sleep for the configured polling interval.
9. Repeat until the bot is stopped.

The polling loop must consume minimal CPU and memory and must never become a busy loop.

---

# CLI Dashboard

During every polling cycle, print a live dashboard.

The number of recent polling results shown on the screen must be configurable.

Example configuration:

```yaml
cli:

    max_visible_polls: 3
```

Default:

```
3
```

If configured as:

```
5
```

the CLI should always display the latest five polling cycles.

Older entries should automatically scroll off the screen.

Example:

```
==========================================================================

POLL #101

Time            : 10:15:00

Price           : 1934.20

MACD            : 1.24

Signal          : 1.10

Histogram       : 0.14

RSI             : 61.82

Signal          : BUY

Trade           : Waiting

Position        : None

PnL             : 0.00

==========================================================================

POLL #102

Time            : 10:15:30

Price           : 1934.75

MACD            : 1.31

Signal          : 1.16

Histogram       : 0.15

RSI             : 62.14

Signal          : BUY

Trade           : Waiting

Position        : None

PnL             : 0.00

==========================================================================

POLL #103

Time            : 10:16:00

Price           : 1935.15

MACD            : 1.42

Signal          : 1.28

Histogram       : 0.14

RSI             : 63.01

Signal          : BUY

Trade           : BUY ORDER PLACED

Position        : LONG

PnL             : +0.00

==========================================================================
```

BUY should appear in Green.

SELL should appear in Red.

EXIT should appear in Magenta.

NO SIGNAL should appear in Yellow.

---

# Runtime Logging

Each polling cycle must log:

* Poll Number
* Timestamp
* Current Price
* MACD
* Signal Line
* Histogram
* RSI
* Generated Signal
* Position Status
* Order Status
* PnL
* Errors (if any)

Logs must be written to:

```
logs/trading.log
```

using rotating log files.

---

# Restart Behaviour

Running:

```bash
python start.py
```

multiple times should never create multiple trading processes.

Instead:

1. Detect existing process.
2. Stop the previous bot gracefully.
3. Reload the latest configuration.
4. Print the active configuration.
5. Start a new polling loop.
6. Resume trading using the updated configuration.

This ensures configuration changes take effect immediately after restarting without requiring manual process cleanup.

---

# Shutdown Behaviour

Running:

```bash
python stop.py
```

must:

* Stop the polling loop.
* Close all Dhan API connections.
* Flush pending log messages.
* Release resources.
* Save the last runtime status.
* Exit cleanly.

Display:

```
Stopping Trading Engine...

Trading Engine Stopped Successfully.
```
