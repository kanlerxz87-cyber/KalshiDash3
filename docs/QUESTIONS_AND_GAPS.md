# Questions, Information & Answers (and Gaps)

This is the required list of questions, the information needed, and the answers we have —
organized so any decision can be made only on confirmed information, with explicit gaps and
suggestions for discovering the missing information. Items marked **UNVERIFIED** could not be
confirmed from an official source and must not be treated as fact.

## A. Information we already have (confirmed)

| # | Question | Information available | Answer | Source |
|---|----------|------------------------|--------|--------|
| A1 | What is the Kalshi demo REST base URL? | Project spec + Kalshi demo endpoints | `https://external-api.demo.kalshi.co/trade-api/v2` (recommended); `https://demo-api.kalshi.co/trade-api/v2` (alternate) | Project spec (Kalshi demo endpoint) |
| A2 | What is the WebSocket demo URL? | Project spec | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`; `wss://demo-api.kalshi.co/trade-api/ws/v2` | Project spec (Kalshi demo endpoint) |
| A3 | How is the API authenticated? | Official SDK | Bearer token: `Authorization: Bearer <key>` | Official SDK `kalshi-python` 2.1.4, `api_client.py` — https://pypi.org/project/kalshi-python/ |
| A4 | What REST endpoints exist for events/markets? | Official SDK | `/events`, `/events/{event_ticker}`, `/events/{event_ticker}/metadata`, `/markets`, `/markets/{ticker}`, `/markets/{ticker}/orderbook`, `/series/{ticker}/markets/{market_ticker}/candlesticks`, `/markets/trades` | Official SDK `events_api.py`, `markets_api.py` |
| A5 | What endpoints exist for portfolio/trading? | Official SDK | `/portfolio/balance`, `/portfolio/positions`, `/portfolio/orders` (GET/POST/DELETE), `/portfolio/fills`, `/portfolio/settlements`, `/exchange/status` | Official SDK `portfolio_api.py`, `exchange_api.py` |
| A6 | What fields describe a market's price/liquidity? | Official SDK | `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`, `volume`, `volume_24h`, `result`, `status`; order book levels `{price, count}` | Official SDK `models/market.py`, `models/orderbook_level.py` |
| A7 | How is a market's resolution represented? | Official SDK | `Market.result` plus `status == "settled"` / `"determined"` | Official SDK `models/market.py` |
| A8 | What candlestick interval values are supported? | Official SDK | `period_interval` e.g. `1m`, `5m`, `1h`, `1d` | Official SDK `markets_api.py` `get_market_candlesticks` |
| A9 | What are the order/event/market status enums? | Official SDK | Order: `resting/canceled/executed/pending`; Event: `open/closed/settled`; Market: `initialized/active/closed/settled/determined` | Official SDK `models/order.py`, `event.py`, `market.py` |
| A10 | What unit is the balance in? | Official SDK | Cents | Official SDK `models/get_balance_response.py` |

## B. Questions we cannot yet answer (GAPS → discover missing info)

| # | Question | What we need to know | Current status | Suggestion to discover the missing information |
|---|----------|----------------------|----------------|-------------------------------------------------|
| B1 | Which Kalshi `series_ticker`s belong to **gas prices, elections, culture, crypto, golf**? | The authoritative series tickers per topic | **UNVERIFIED** — the API was unreachable from the sandbox, so the live series list could not be pulled | Fetch `GET /series` (or scan event `series_ticker` + `title`) in the browser and map series → topic; publish the confirmed mapping to `site/data/categories.json`. Until confirmed, the app uses a *proposed* keyword mapping, clearly labeled. |
| B2 | Does the Kalshi demo API allow **browser cross-origin (CORS)** requests for trading and portfolio? | Whether `POST /portfolio/orders` and `GET /portfolio/*` succeed from a browser | **UNVERIFIED** — cannot be tested from the sandbox | Attempt an authenticated call from the browser via the dashboard; if it fails with a CORS error, deploy a lightweight backend proxy (GitHub Actions or a small server) that forwards Kalshi requests. |
| B3 | Is a demo API key required for **read** endpoints, or are reads fully public? | Whether `/events`, `/markets`, order book, and candlesticks work without `Authorization` | **UNVERIFIED** — SDK lists `bearerAuth` on GETs, but Kalshi's ecosystem describes public reads | Test unauthenticated reads in the browser. The dashboard already sends `Authorization` only when a key is set; confirm the no-key path works and document it. |
| B4 | What is the **real "dollar amount"** of an event? | A dollar-value field or a reliable conversion | **UNVERIFIED** — Kalshi exposes no direct dollar-amount field on events/markets | Confirm whether Kalshi provides any dollar/notional field (e.g., in event metadata or a newer field). Until then, rank by `volume_24h` and show estimated $ volume = `volume_24h × last_price`, labeled as an estimate. |
| B5 | Which markets are **live (trading) right now**, and what is their current liquidity? | Live status + order-book depth per market | **UNVERIFIED** — requires a live connection | The dashboard fetches `status=open` events and each market's order book at runtime in the browser; populate and review the live table. |
| B6 | What are the **fees and settlement rules** for the demo account? | Fee schedule, settlement timing, PnL calculation | **UNVERIFIED** — `Position` exposes `fees_paid`, `realized_pnl`, `total_cost`, but the fee rules are not in the SDK | Confirm fee/settlement rules from Kalshi's official documentation, then encode them in the portfolio PnL logic. |
| B7 | What is the **demo account's funding / balance** and available margin? | Balance and margin for sizing | **UNVERIFIED** — requires a demo API key | Provide the demo API key in site settings; the dashboard reads `GET /portfolio/balance`. |
| B8 | What is the **maximum order size / position limits** per market? | `cap_count`, position caps, contract multipliers | **UNVERIFIED** — `cap_count` exists on the Market model but its semantics are not documented in the SDK | Confirm from Kalshi docs; display `cap_count` and any documented limits; block/warn on over-limit orders. |
| B9 | How often does the demo API **update** prices and the order book, and are there rate limits? | Poll interval + rate limits | **UNVERIFIED** — not in the SDK | Test live update cadence in the browser; respect Kalshi rate limits; the dashboard polls at a conservative default and makes the interval configurable. |
| B10 | Are there **WebSocket** streams we should use instead of polling for lower latency? | WS channel list and subscription format | **UNVERIFIED** — WS endpoint URLs are given, but the subscription schema is not verified | Verify the WS protocol from Kalshi's official docs/spec; if available, switch the "seconds" view and order book to WS push instead of polling. |

## C. Decision rules

- **Do not act on an UNVERIFIED value** as if it were confirmed. In the dashboard tables, an
  unverified value is left blank and flagged.
- **Do not fabricate** live market or portfolio numbers. Where the live API is the only
  source, the table is populated at runtime from the API (with the endpoint URL as the source
  link); if the fetch fails, the row is flagged.
- **Category mapping, dollar-amount ranking, CORS, and fee rules** are the four highest-impact
  gaps. Resolve B1–B4 before making strategy or sizing decisions.
