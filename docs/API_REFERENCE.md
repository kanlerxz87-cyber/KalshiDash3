# Kalshi Demo REST Trade API — Verified Reference

**Base URL (recommended demo endpoint, per project spec):**
`https://external-api.demo.kalshi.co/trade-api/v2`

**Alternate supported demo endpoint:** `https://demo-api.kalshi.co/trade-api/v2`

**WebSocket (demo):** `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` and
`wss://demo-api.kalshi.co/trade-api/ws/v2`

**Source of truth for this document:** the official Kalshi Python SDK
**`kalshi-python` version 2.1.4**, author "Kalshi Support", summary "Kalshi Trading API",
published on PyPI. The SDK is generated from Kalshi's OpenAPI spec, so its resource paths,
query parameters, and model fields are an official, verifiable reference for the REST API.

- PyPI package: https://pypi.org/project/kalshi-python/
- SDK home/repository link on PyPI: https://github.com/Kalshi/exchange-infra
- Kalshi GitHub organization (official): https://github.com/Kalshi

> **Verification note:** The Kalshi API servers (`*.kalshi.co`) were **not reachable from the
> build sandbox** (TLS handshake failed with `SSL_ERROR_SYSCALL`). The endpoint paths,
> parameters, enums, and field names below were therefore verified against the official SDK
> distribution downloaded from `files.pythonhosted.org`, **not** by live calls. Live values are
> fetched by the dashboard at runtime in the user's browser. See
> [`VERIFICATION_LOG.md`](VERIFICATION_LOG.md).

## Authentication

- Scheme: **Bearer token**. Set the `Authorization: Bearer <key>` header.
  (Verified: `kalshi_python/api_client.py` → `set_bearer_token()` sets
  `Authorization: Bearer <token>`.)
- The SDK lists `bearerAuth` on GET endpoints too; read endpoints (`/events`, `/markets`,
  order book, candlesticks) are also documented as public reads by Kalshi's ecosystem
  (e.g. the `@pipeworx/mcp-kalshi` description: "no auth on public reads"). The dashboard
  sends `Authorization` only when a demo API key is configured, and reads market data
  without a key.

## Verified REST endpoints

| Method | Path | Purpose | Verified query params |
|--------|------|---------|------------------------|
| GET | `/events` | List events | `limit`, `cursor`, `with_nested_markets`, `status`, `series_ticker`, `min_close_ts` |
| GET | `/events/{event_ticker}` | Get one event | — |
| GET | `/events/{event_ticker}/metadata` | Get event metadata | — |
| GET | `/markets` | List markets | `limit`, `cursor`, `event_ticker`, `series_ticker`, `max_close_ts`, `min_close_ts`, `status`, `tickers` |
| GET | `/markets/{ticker}` | Get one market | — |
| GET | `/markets/{ticker}/orderbook` | Order book (liquidity) | — |
| GET | `/series/{ticker}/markets/{market_ticker}/candlesticks` | OHLCV candles | `start_ts`, `end_ts`, `period_interval` (e.g. `1m`, `5m`, `1h`, `1d`) |
| GET | `/markets/trades` | Public trade prints | `limit`, `cursor`, `ticker`, `min_ts`, `max_ts` |
| GET | `/portfolio/balance` | Account balance | — |
| GET | `/portfolio/positions` | Open positions | `limit`, `cursor` |
| GET | `/portfolio/orders` | Orders | `limit`, `cursor`, `status` |
| GET | `/portfolio/orders/{order_id}` | One order | — |
| POST | `/portfolio/orders` | Create order | (body) |
| DELETE | `/portfolio/orders/{order_id}` | Cancel order | — |
| GET | `/portfolio/fills` | Fills | `limit`, `cursor`, `ticker` |
| GET | `/portfolio/settlements` | Settlements | — |
| GET | `/exchange/status` | Exchange status | — |

(All paths verified from the SDK's `events_api.py`, `markets_api.py`, `portfolio_api.py`,
and `exchange_api.py`.)

## Verified model fields

### Event
`event_ticker`, `series_ticker`, `sub_title`, `title`, `status`, `markets[]`
- `status` enum: **`open` | `closed` | `settled`**

### Market
`ticker`, `series_ticker`, `event_ticker`, `title`, `subtitle`, `open_time`, `close_time`,
`expiration_time`, `status`, `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`,
`volume`, `volume_24h`, `result`, `can_close_early`, `cap_count`
- `status` enum: **`initialized` | `active` | `closed` | `settled` | `determined`**

### Order book (liquidity)
- Response: `{ "orderbook": { "true": [ {price, count} ], "false": [ {price, count} ] } }`
  where `true` = YES side, `false` = NO side.
- Level: `price` (cents), `count` (number of contracts at that price).

### Candlestick
`start_ts`, `end_ts`, `open`, `high`, `low`, `close`, `volume`

### Portfolio
- `GET /portfolio/balance` → `{ "balance": <cents> }`
- `GET /portfolio/positions` → `Position`: `ticker`, `event_ticker`, `market_result`,
  `realized_pnl`, `resting_order_count`, `position`, `fees_paid`, `total_cost`
- `GET /portfolio/orders` → `Order`: `order_id`, `client_order_id`, `ticker`, `side`,
  `action`, `type`, `status`, `yes_price`, `no_price`, `count`, `remaining_count`,
  `expiration_time`, `created_time`, `updated_time`
- `GET /portfolio/fills` → `Fill`: `fill_id`, `order_id`, `ticker`, `side`, `action`,
  `count`, `price`, `is_taker`, `created_time`

## Verified enums

| Domain | Field | Values |
|--------|-------|--------|
| Order | `side` | `yes` \| `no` |
| Order | `action` | `buy` \| `sell` |
| Order | `type` | `limit` \| `market` |
| Order | `status` | `resting` \| `canceled` \| `executed` \| `pending` |
| Fill | `side` | `yes` \| `no` |
| Fill | `action` | `buy` \| `sell` |
| Event | `status` | `open` \| `closed` \| `settled` |
| Market | `status` | `initialized` \| `active` \| `closed` \| `settled` \| `determined` |

## Notes on the dashboard's use of these fields

- **"Highest dollar amount" events:** Kalshi exposes **no direct dollar-amount field** on
  events/markets. The dashboard ranks by `volume_24h` (contracts traded in 24h) and displays
  an **estimated dollar volume** = `volume_24h × last_price`, clearly labeled as an estimate.
  This is a flagged gap — see [`QUESTIONS_AND_GAPS.md`](QUESTIONS_AND_GAPS.md).
- **Liquidity:** displayed from `GET /markets/{ticker}/orderbook` — the `count` at each price
  level is the number of contracts available at that price, which is exactly what the project
  asks for.
- **Resolution (yes/no):** `Market.result` and `Market.status == "settled"` carry the
  resolution; the dashboard tracks each live event until it settles and records yes/no.
- **Price graph timeframes:** minutes/hours use `/series/{ticker}/markets/{market_ticker}/candlesticks`
  with `period_interval` (`1m`, `5m`, `1h`). The "seconds" view polls `last_price` client-side
  at ~1s intervals because the candlestick endpoint has no sub-minute interval.
