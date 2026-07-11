# SRP Dhan Helper

This file explains how to use `Dhan_SRP.py` as a single reusable Dhan utility in any other repo or algo.

## Purpose

`Dhan_SRP.py` is designed to act as one portable trading module that you can copy into another repo and import inside any stock or options algo.

Use it when you want one file to handle:

- Dhan login and client setup
- static symbol-to-security ID lookup via `get_security_id_by_symbol()`
- instrument lookup
- stock order placement
- option contract lookup
- order modify and cancel flows
- margin checks
- option-chain analysis
- portfolio and funds access
- strategy helpers such as straddle, strangle, and iron condor

## Minimum Setup In Another Repo

Copy these into your other repo:

- `Dhan_SRP.py`
- this guide if you want reference usage

Install the required packages in that repo environment:

```bash
pip install dhanhq pandas numpy requests pytz mibian
```

If your installed `dhanhq` SDK supports `DhanContext`, `MarketFeed`, and `OrderUpdate`, the advanced feed helpers will work too.

## Credentials

You can initialize `Dhansrp` in three ways.

### 1. Direct credentials

```python
from Dhan_SRP import Dhansrp

dhan = Dhansrp(ClientCode="YOUR_CLIENT_ID", token_id="YOUR_ACCESS_TOKEN")
```

### 2. Environment variables

```bash
export DHAN_CLIENT_ID="YOUR_CLIENT_ID"
export DHAN_ACCESS_TOKEN="YOUR_ACCESS_TOKEN"
```

```python
from Dhan_SRP import Dhansrp

dhan = Dhansrp()
```

### 3. Config file

Create a config JSON file such as:

```json
{
  "client_id": "YOUR_CLIENT_ID",
  "access_token": "YOUR_ACCESS_TOKEN"
}
```

Then use:

```python
from Dhan_SRP import Dhansrp

dhan = Dhansrp(config_path="config.json")
```

## Recommended Initialization Pattern

For most algos, use:

```python
from Dhan_SRP import Dhansrp

dhan = Dhansrp(
    config_path="config.json",
    enable_file_logging=False,
    persist_instrument_file=False,
)
```

This keeps the module more portable across local systems, cloud runners, and other repos.

## Best Way To Structure Any Algo

Use `Dhan_SRP.py` only as your broker/data layer.

Your algo file should usually do this:

1. initialize `Dhansrp`
2. fetch market inputs
3. run your signal logic
4. prepare or validate orders
5. place orders only if your algo conditions pass

Simple pattern:

```python
from Dhan_SRP import Dhansrp


def run_algo():
    dhan = Dhansrp(config_path="config.json")

    # 1. Read data
    snapshot = dhan.get_option_chain_snapshot(underlying="NIFTY")

    # 2. Signal logic
    spot = snapshot["spot"]
    if spot > 25000:
        result = dhan.place_long_call(
            underlying="NIFTY",
            dry_run=True,
        )
        return result

    return {"status": "no_trade"}


if __name__ == "__main__":
    print(run_algo())
```

## Core Usage Patterns

### 1. Get security ID from symbol (static map)

Use this when you need an NSE stock `security_id` from the built-in static map.

```python
security_id = dhan.get_security_id_by_symbol("RELIANCE")
print(security_id)  # 2885
```

If symbol is not available in the static map, it raises `ValueError`.

### 2. Prepare an equity intraday limit order

Use this when you want a stock trade preview and validation before placing.

```python
preview = dhan.prepare_equity_limit_order(
    symbol="HDFCBANK",
    price=1800.0,
    quantity=10,
    transaction_type="BUY",
    product_type="INTRADAY",
    exchange_segment="NSE_EQ",
)

print(preview["preview"])
print(preview["validation"])
```

### 3. Place an equity order directly

```python
result = dhan.place_stock_order(
    symbol="HDFCBANK",
    quantity=10,
    transaction_type="BUY",
    order_type="LIMIT",
    product_type="INTRADAY",
    price=1800.0,
    dry_run=True,
)
```

Set `dry_run=False` only when you want to send the live order.

### 4. Modify or cancel an order

```python
modify_response = dhan.modify_order_request(
    order_id="YOUR_ORDER_ID",
    order_type="LIMIT",
    quantity=10,
    price=1801.0,
)

cancel_response = dhan.cancel_order_request(order_id="YOUR_ORDER_ID")
```

### 5. Buy one NIFTY call and one NIFTY put

Use this for a straddle-like starting point.

```python
pair = dhan.buy_call_put_pair(
    underlying="NIFTY",
    dry_run=True,
)

print(pair)
```

If you want a specific strike pair:

```python
pair = dhan.buy_call_put_pair(
    underlying="NIFTY",
    call_strike=25000,
    put_strike=25000,
    dry_run=True,
)
```

### 6. Buy only one call

```python
call_order = dhan.place_long_call(
    underlying="NIFTY",
    strike=25000,
    dry_run=True,
)
```

### 7. Buy only one put

```python
put_order = dhan.place_long_put(
    underlying="NIFTY",
    strike=25000,
    dry_run=True,
)
```

### 8. Place an option order using a known expiry and strike

```python
option_order = dhan.place_option_order(
    underlying="NIFTY",
    expiry="2026-07-30",
    strike=25000,
    option_type="CE",
    transaction_type="BUY",
    product_type="INTRADAY",
    order_type="LIMIT",
    price=120.0,
    dry_run=True,
)
```

### 9. Get ATM call and put details first

```python
atm = dhan.get_atm_option_pair(underlying="NIFTY")
print(atm)
```

This is useful when your own algo decides whether to use ATM, ITM, or OTM contracts.

### 10. Use straddle and strangle helpers

```python
straddle = dhan.place_atm_straddle(
    underlying="NIFTY",
    dry_run=True,
)

strangle = dhan.place_strangle(
    underlying="NIFTY",
    call_offset=2,
    put_offset=2,
    dry_run=True,
)
```

### 11. Analyze or place an iron condor

```python
analysis = dhan.analyze_iron_condor(
    underlying="NIFTY",
)

execution = dhan.place_iron_condor(
    underlying="NIFTY",
    dry_run=True,
)
```

## Basket And Multi-Leg Execution

If your algo builds its own legs, use `place_multi_leg_orders()`.

```python
ce_security_id = str(dhan.get_security_id_by_symbol("RELIANCE"))
pe_security_id = str(dhan.get_security_id_by_symbol("INFY"))

orders = [
    {
        "security_id": ce_security_id,
        "symbol": "RELIANCE",
        "exchange_segment": "NSE_EQ",
        "transaction_type": "BUY",
        "quantity": 1,
        "order_type": "LIMIT",
        "product_type": "CNC",
        "price": 2880.0,
        "instrument_name": "EQUITY",
    },
    {
        "security_id": pe_security_id,
        "symbol": "INFY",
        "exchange_segment": "NSE_EQ",
        "transaction_type": "BUY",
        "quantity": 1,
        "order_type": "LIMIT",
        "product_type": "CNC",
        "price": 1500.0,
        "instrument_name": "EQUITY",
    },
]

margin = dhan.check_margin_for_orders(orders)
print(margin)

result = dhan.place_multi_leg_orders(orders, dry_run=True)
print(result)
```

## Market Data And Analysis Helpers

### Option chain snapshot

```python
snapshot = dhan.get_option_chain_snapshot(underlying="NIFTY")
print(snapshot["spot"])
print(snapshot["atm_strike"])
print(snapshot["chain"])
```

### Full normalized option-chain DataFrame

```python
expiries = dhan.get_expiry_dates(13)
chain_df, spot = dhan.fetch_option_chain_df(
    under_security_id=13,
    expiry=expiries[0],
)
```

### Historical data and indicators

```python
reliance_security_id = str(dhan.get_security_id_by_symbol("RELIANCE"))

history = dhan.get_history_df(
    security_id=reliance_security_id,
    exchange_segment="NSE_EQ",
    instrument_type="EQUITY",
    from_date="2026-01-01",
    to_date="2026-07-01",
    interval="daily",
)

history = dhan.add_basic_indicators(history)
print(history.tail())
```

## Portfolio, Funds, And Account Monitoring

```python
summary = dhan.get_portfolio_summary()

print(summary["summary"])
print(summary["funds"])
print(summary["positions"])
```

## Advanced Dhan Features In This File

You can also use these directly when your algo needs them:

- `place_forever_order()`
- `get_forever_orders()`
- `cancel_forever_order()`
- `place_super_order()`
- `modify_super_order()`
- `cancel_super_order()`
- `get_super_orders()`
- `convert_position()`
- `create_market_feed()`
- `create_order_update_feed()`

## Recommended Safe Workflow

For any new algo, use this order of operations:

1. resolve security IDs or contracts first (`get_security_id_by_symbol()` for supported NSE stocks)
2. inspect preview output
3. inspect validation output
4. inspect margin for single-leg or basket orders
5. run with `dry_run=True`
6. switch to `dry_run=False` only after confirming your signal and payload

## Good Pattern For Reuse In Another Repo

In another repo, keep `Dhan_SRP.py` inside a folder like:

```text
my_algo_repo/
  algos/
    breakout.py
    straddle.py
  broker/
    Dhan_SRP.py
  config.json
```

Then import like this:

```python
from broker.Dhan_SRP import Dhansrp
```

This keeps your algo logic separate from your broker utility.

## Suggested Separation Of Responsibilities

Use `Dhan_SRP.py` for:

- login
- market data access
- contract resolution
- margin checks
- order placement
- position and portfolio access

Keep your algo file responsible for:

- entry rules
- exit rules
- time filters
- stop-loss logic
- target logic
- daily risk limits
- re-entry rules

That separation makes it easier to reuse the same `Dhan_SRP.py` in multiple repos.

## Example: Stock Algo In Another Repo

```python
from broker.Dhan_SRP import Dhansrp


def run_hdfcbank_intraday():
    dhan = Dhansrp(config_path="config.json")

    order = dhan.place_stock_order(
        symbol="HDFCBANK",
        quantity=10,
        transaction_type="BUY",
        order_type="LIMIT",
        product_type="INTRADAY",
        price=1800.0,
        dry_run=True,
    )
    return order
```

## Example: Options Algo In Another Repo

```python
from broker.Dhan_SRP import Dhansrp


def run_nifty_straddle():
    dhan = Dhansrp(config_path="config.json")

    result = dhan.place_atm_straddle(
        underlying="NIFTY",
        dry_run=True,
    )
    return result
```

## Practical Notes

- Keep `dry_run=True` while testing new algos.
- For F&O, always verify lot size and margin before live placement.
- For live order APIs on Dhan, make sure your static IP requirements are already handled on your side.
- For market-data and option-chain APIs, make sure your Dhan data plan supports those calls.
- If you move this file into another repo, retest imports and SDK compatibility once in that environment.

## If You Want To Extend This File Later

Good future additions inside `Dhan_SRP.py` would be:

- explicit stop-loss and target orchestration helpers
- strategy-level square-off helpers
- trade journaling to JSON or CSV
- risk manager wrappers such as max daily loss or max open positions
- basket execution with rollback rules

## Bottom Line

Treat `Dhan_SRP.py` as your broker adapter and reusable trading toolbox.

For any new repo or algo, copy the file, initialize `Dhansrp`, keep your signal logic in separate algo files, and call the methods from this module for data, validation, margin, and order execution.