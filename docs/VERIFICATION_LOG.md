# Verification Log

Record of how each fact was verified, the sources used, and any irregularities. Nothing is
marked verified without an official source. Unverified items are flagged, never inferred.

## Environment & connectivity check (performed 2026-11-20)

| Check | Result | Evidence |
|-------|--------|----------|
| Reach `https://external-api.demo.kalshi.co/trade-api/v2` | **FAIL** — TLS `SSL_ERROR_SYSCALL` (exit 35) | `curl -sv` handshake: `OpenSSL SSL_connect: SSL_ERROR_SYSCALL` |
| Reach `https://kalshi.com` | **FAIL** — exit 35 | `curl` |
| Reach `https://docs.kalshi.com` | **FAIL** — exit 35 | `curl` |
| DNS for `external-api.demo.kalshi.co` | resolves (AWS NLB, us-west-2) | `getent hosts` |
| Reach `https://api.github.com` | OK (200) | `curl` |
| Reach `https://registry.npmjs.org` | OK (200) | `curl` |
| Reach `https://pypi.org` | OK (200) | `curl` |

**Irregularity flagged:** The sandbox can reach only `github.com`,
`codeload.github.com`, `api.github.com`, `registry.npmjs.org`, `pypi.org`,
`files.pythonhosted.org`. Kalshi's API servers are unreachable. Therefore **no live Kalshi
data could be pulled from the sandbox**, and no live market/portfolio value in this project is
stated as fact. Live data is loaded by the dashboard **in the user's browser**.

## Official source used for all API facts

- **Package:** `kalshi-python` **2.1.4**
- **Author:** Kalshi Support
- **Summary:** Kalshi Trading API
- **PyPI:** https://pypi.org/project/kalshi-python/
- **PyPI JSON:** https://pypi.org/pypi/kalshi-python/2.1.4/json
- **Wheel downloaded from:** `files.pythonhosted.org` (reachable) — SHA verified by successful
  unzip and file listing.
- **SDK home/repository link on PyPI:** https://github.com/Kalshi/exchange-infra
- **Kalshi official GitHub org:** https://github.com/Kalshi

The SDK is generated from Kalshi's OpenAPI spec; its resource paths, query parameters, and
model fields are an official reference for the REST Trade API.

## Line-by-line verification record

| # | Fact verified | Where verified (SDK source file) | Verdict |
|---|---------------|----------------------------------|---------|
| 1 | Auth = Bearer token (`Authorization: Bearer <token>`) | `kalshi_python/api_client.py` → `set_bearer_token()` | Verified |
| 2 | `GET /events` path and query params (`limit`, `cursor`, `with_nested_markets`, `status`, `series_ticker`, `min_close_ts`) | `kalshi_python/api/events_api.py` → `_get_events_serialize` (`resource_path='/events'`) | Verified |
| 3 | `GET /events/{event_ticker}` | `events_api.py` → `resource_path='/events/{event_ticker}'` | Verified |
| 4 | `GET /events/{event_ticker}/metadata` | `events_api.py` → `resource_path='/events/{event_ticker}/metadata'` | Verified |
| 5 | `GET /markets` path and params (`limit`, `cursor`, `event_ticker`, `series_ticker`, `max_close_ts`, `min_close_ts`, `status`, `tickers`) | `kalshi_python/api/markets_api.py` → `_get_markets_serialize` (`resource_path='/markets'`) | Verified |
| 6 | `GET /markets/{ticker}` | `markets_api.py` → `resource_path='/markets/{ticker}'` | Verified |
| 7 | `GET /markets/{ticker}/orderbook` | `markets_api.py` → `resource_path='/markets/{ticker}/orderbook'` | Verified |
| 8 | `GET /series/{ticker}/markets/{market_ticker}/candlesticks` with `period_interval` (e.g. `1m`, `5m`, `1h`, `1d`) | `markets_api.py` → `get_market_candlesticks` (docstring lists intervals; `resource_path='/series/{ticker}/markets/{market_ticker}/candlesticks'`) | Verified |
| 9 | `GET /markets/trades` params (`limit`, `cursor`, `ticker`, `min_ts`, `max_ts`) | `markets_api.py` → `_get_trades_serialize` (`resource_path='/markets/trades'`) | Verified |
| 10 | `GET /portfolio/balance` → `{balance}` in cents | `portfolio_api.py` (`resource_path='/portfolio/balance'`); `models/get_balance_response.py` | Verified |
| 11 | `GET /portfolio/positions` → Position fields | `portfolio_api.py` (`resource_path='/portfolio/positions'`); `models/position.py` | Verified |
| 12 | `GET/POST/DELETE /portfolio/orders` | `portfolio_api.py` (`resource_path='/portfolio/orders'`, `'/portfolio/orders/{order_id}'`) | Verified |
| 13 | `GET /portfolio/fills`, `/portfolio/settlements` | `portfolio_api.py` | Verified |
| 14 | `GET /exchange/status` | `exchange_api.py` (`resource_path='/exchange/status'`) | Verified |
| 15 | Event status enum `open/closed/settled` | `models/event.py` → `status_validate_enum` | Verified |
| 16 | Market status enum `initialized/active/closed/settled/determined` | `models/market.py` → `status_validate_enum` | Verified |
| 17 | Market fields (`yes_bid/yes_ask/no_bid/no_ask/last_price/volume/volume_24h/result/...`) | `models/market.py` → `__properties` | Verified |
| 18 | Order book level `{price, count}`; response keys `true`/`false` | `models/orderbook_level.py`; `models/get_market_orderbook_response_orderbook.py` | Verified |
| 19 | Candlestick fields (`start_ts/end_ts/open/high/low/close/volume`) | `models/candlestick.py` | Verified |
| 20 | Order `side` enum `yes/no`, `action` `buy/sell`, `type` `limit/market`, `status` `resting/canceled/executed/pending` | `models/order.py` validators | Verified |
| 21 | Fill `side` `yes/no`, `action` `buy/sell`; fields `fill_id/ticker/count/price/...` | `models/fill.py` | Verified |
| 22 | SDK default host = `api.elections.kalshi.com/trade-api/v2`; demo host listed = `demo-api.elections.kalshi.com/trade-api/v2` | `configuration.py` (`_base_path`) | Verified (SDK defaults); the project-spec demo URLs are used as primary |

## Items NOT verified (flagged, left blank / not inferred)

| # | Item | Why unverified | Where flagged |
|---|------|----------------|---------------|
| 1 | Live event/market values (prices, volume, liquidity) | Kalshi API unreachable from sandbox | Flagged for Review page; dashboard fetches live in-browser |
| 2 | Live portfolio values (balance, positions, PnL) | Requires demo API key + live API | Flagged for Review page; Portfolio page requires key |
| 3 | Series-ticker → topic mapping (gas/elections/culture/crypto/golf) | Requires live series list | Flagged for Review page; configurable mapping |
| 4 | CORS support for browser trading | Cannot test cross-origin from sandbox | Flagged for Review page; Suggestion S2 |
| 5 | Whether reads require auth | Not confirmed from sandbox | Flagged for Review page; Question B3 |
| 6 | Fee schedule and settlement rules | Not in SDK; docs unreachable | Flagged for Review page; Question B6 |
| 7 | `cap_count` semantics and position limits | Not documented in SDK | Flagged for Review page; Question B8 |
| 8 | Rate limits and update cadence | Not in SDK; docs unreachable | Flagged for Review page; Question B9 |
| 9 | WebSocket subscription schema | WS URLs given; schema unverified | Flagged for Review page; Question B10 |

## Reproduction

To re-verify the SDK facts:

```bash
curl -s https://pypi.org/pypi/kalshi-python/2.1.4/json   # confirm version/author
# download the wheel from the JSON 'urls' and unzip; inspect the api/ and models/ dirs
```

To confirm live data (requires a reachable network and, for portfolio, a demo API key): open
the deployed dashboard and observe the live tables and graphs.
