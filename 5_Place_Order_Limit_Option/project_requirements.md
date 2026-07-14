# Build a Production-Ready Dhan Trading API (Python + FastAPI)

## Objective

Build a lightweight, production-ready Python FastAPI application that can place **LIMIT BUY/SELL orders** for **Dhan Stocks and Options**.

The application will be deployed on a small cloud server (1GB RAM), so keep memory usage low and avoid unnecessary dependencies.

Use the existing project files as references instead of rewriting everything.

Reference files:

* `Dhan_SRP.py` (primary trading implementation)
* `srp_dhan_helper.md` (API documentation and helper reference)
* `security_id/api-scrip-master.csv` (security master)

---

# Tech Stack

* Python 3.12+
* FastAPI
* Uvicorn
* Pandas (only for loading security master)
* PyYAML
* Requests

Do NOT use:

* Celery
* Redis
* RabbitMQ
* SQL database
* Docker
* Async message queue

Keep everything simple.

---

# Project Structure

```
project/

│
├── app/
│   ├── api.py
│   ├── order_service.py
│   ├── dhan_client.py
│   ├── config_loader.py
│   ├── logger.py
│   └── utils.py
│
├── config/
│   └── config.yaml
│
├── security_id/
│   └── api-scrip-master.csv
│
├── logs/
│   └── trading.log
│
├── Dhan_SRP.py
├── srp_dhan_helper.md
│
├── start.py
├── stop.py
├── logs.py
├── requirements.txt
└── README.md
```

---

# Use Existing Reference Code

Do NOT reinvent Dhan API logic.

Use

```
Dhan_SRP.py
```

as the primary reference.

Use

```
srp_dhan_helper.md
```

for request formats, payloads, endpoints, helper methods and validation.

Only wrap existing logic cleanly into a FastAPI service.

---

# Configuration File

Create

```
config/config.yaml
```

Example:

```yaml
dhan:
  client_id: ""
  access_token: ""

trading:

  exchange: NSE

  segment: EQUITY

  stock_name: HDFCBANK

  security_id: ""

  quantity: 1

  transaction_type: BUY

  order_type: LIMIT

  limit_price: 1890.50

risk:

  target_percent: 2

  stoploss_percent: 1

  trailing_sl: false

cloud:

  log_level: INFO
```

Nothing should be hardcoded.

Everything must come from this config.

---

# Security Master

Read

```
security_id/api-scrip-master.csv
```

Find security ID automatically using

Stock Name

Example:

```
HDFCBANK
RELIANCE
SBIN
INFY
```

The application should automatically lookup

```
security_id
```

from the CSV.

No hardcoding.

---

# FastAPI Endpoints

Create clean REST APIs.

## Health

```
GET /health
```

Returns

```
{
  "status":"running"
}
```

---

## Place Order

```
POST /place-order
```

Reads configuration.

Automatically

* loads config
* finds security id
* places LIMIT order

Returns

```
{
  "status":"success",
  "order_id":"..."
}
```

---

## Reload Config

```
POST /reload-config
```

Reload YAML without restarting server.

---

# Limit Order

Support only

LIMIT orders.

Inputs:

* BUY
* SELL
* STOCK
* OPTION

Fields

* quantity
* limit price
* exchange
* security id
* product type
* transaction type

Must follow Dhan API exactly.

---

# TP / SL

Store in config only.

Example

```
tp_percent

sl_percent
```

Current version only places LIMIT order.

Keep TP/SL values available for future implementation.

Do not implement bracket logic yet.

---

# Logging

Create

```
logs/trading.log
```

Log

* startup
* config load
* API request
* order request
* order response
* API errors
* exceptions

Use rotating log file.

---

# logs.py

Running

```
python logs.py
```

should continuously print

```
logs/trading.log
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

should launch

FastAPI

```
0.0.0.0

port 7001
```

using Uvicorn.

---

# stop.py

Should gracefully stop the running FastAPI server on cloud.

Avoid force killing whenever possible.

---

# Error Handling

Handle

* Invalid security id
* Invalid stock name
* API timeout
* Dhan authentication failure
* Network error
* Invalid quantity
* Invalid limit price
* Empty configuration

Return proper JSON errors.

---

# Performance

Application should

* load CSV only once
* cache security IDs
* reuse HTTP session
* avoid unnecessary memory allocations
* start quickly
* support deployment on 1GB RAM VPS

---

# requirements.txt

Include only required packages.

Example

```
fastapi
uvicorn
pandas
pyyaml
requests
```

Avoid unnecessary dependencies.

---

# Code Quality

Requirements

* Modular
* Clean architecture
* Type hints
* Docstrings
* No duplicated code
* Production-ready
* Easy to extend later for

  * Market Orders
  * Bracket Orders
  * WebSocket
  * Algo Trading
  * Strategy Engine
  * Scheduler

---

# Deliverables

Generate complete working source code including:

* project structure
* FastAPI application
* configuration loader
* Dhan wrapper
* CSV security lookup
* order service
* logging module
* start.py
* stop.py
* logs.py
* requirements.txt
* README.md

The implementation must use `Dhan_SRP.py` and `srp_dhan_helper.md` as the primary references for Dhan API interactions, while keeping the code modular, production-ready, and optimized for deployment on a low-memory cloud server.
