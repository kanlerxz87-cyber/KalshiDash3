# KalshiDash3 — Executive Summary

## What this project is

KalshiDash3 is a live, interactive dashboard for the **Kalshi prediction-market demo
environment**. It collects, organizes, and analyzes live Kalshi market data for a focused set
of topics, tracks live events through resolution, monitors a demo-account portfolio, executes
trades, and provides a structured place to review suggestions and flagged items before any
change is made.

## Verified platform facts (Kalshi demo Trade API)

| Item | Value | Source |
|------|-------|--------|
| Recommended demo base URL | `https://external-api.demo.kalshi.co/trade-api/v2` | Project spec (Kalshi demo endpoint) |
| Alternate demo base URL | `https://demo-api.kalshi.co/trade-api/v2` | Project spec (Kalshi demo endpoint) |
| WebSocket demo URLs | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2`, `wss://demo-api.kalshi.co/trade-api/ws/v2` | Project spec (Kalshi demo endpoint) |
| Auth scheme | Bearer token (`Authorization: Bearer <key>`) | Official SDK `kalshi-python` 2.1.4, `api_client.py` |
| Official SDK reference | `kalshi-python` 2.1.4, author "Kalshi Support" | https://pypi.org/project/kalshi-python/ |
| Event status values | `open`, `closed`, `settled` | Official SDK `models/event.py` |
| Market status values | `initialized`, `active`, `closed`, `settled`, `determined` | Official SDK `models/market.py` |
| Order side / action | `yes`/`no`, `buy`/`sell`, `limit`/`market` | Official SDK `models/order.py` |
| Balance unit | Cents | Official SDK `models/get_balance_response.py` |

The full endpoint and field reference — verified line-by-line against the official SDK — is in
[`API_REFERENCE.md`](API_REFERENCE.md).

## What the dashboard does

1. **Live event tracking by topic.** Lists Kalshi events filtered to five requested topics —
   **gas prices, elections, culture, crypto, golf** — and ranks them by trading activity
   (`volume_24h`, with an estimated dollar volume). Each event is tracked from `open` until it
   `settles`, recording the **yes/no** resolution from `market.result`.
2. **Live price graphs with selectable timeframes.** For any market, a price chart with
   **x = time** and **y = contract price**, with timeframe selection of **seconds, minutes,
   or hours**. Minutes/hours use Kalshi candlesticks (`period_interval`); seconds polls the
   live `last_price`.
3. **Liquidity display.** Shows the order book — **how many contracts are available at each
   price** — from `GET /markets/{ticker}/orderbook` (YES and NO sides).
4. **Portfolio performance.** Connects to the Kalshi **demo account** (`/portfolio/balance`,
   `/portfolio/positions`, `/portfolio/fills`, `/portfolio/orders`, `/portfolio/settlements`),
   tracks performance, and **categorizes trades** by topic/side/action to support strategy
   analysis.
5. **Trade execution.** Places and cancels orders through `POST /portfolio/orders` and
   `DELETE /portfolio/orders/{order_id}` and tracks fills/settlements.
6. **Suggestions & questions.** A dedicated section lists suggestions for improving
   decision-making, plus the required **questions / information / answers** matrix and the
   suggestions for discovering missing information. See [`SUGGESTIONS.md`](SUGGESTIONS.md) and
   [`QUESTIONS_AND_GAPS.md`](QUESTIONS_AND_GAPS.md).
7. **Flagged for review.** Irregularities and unverified items are published on a clearly
   labeled page with source links so they can be reviewed after the site is live.

## Key constraints and flags (important)

- **Sandbox network restriction (flagged).** The build sandbox **cannot reach `*.kalshi.co`**
  (TLS handshake fails). All live Kalshi data is loaded **client-side in the user's browser**,
  which can reach Kalshi. No live market values were fabricated; where a value could not be
  confirmed from an official source it is left blank and flagged as unverified.
- **CORS risk (flagged).** Browser-direct trading/portfolio calls may be blocked by Kalshi's
  CORS policy; this could not be verified from the sandbox. A backend proxy is suggested as a
  fallback. See [`SUGGESTIONS.md`](SUGGESTIONS.md).
- **Category mapping (flagged).** The mapping of Kalshi `series_ticker`s to the five topics is
  configurable and pre-seeded as *proposed*; it could not be verified against the live API.
- **"Highest dollar amount" (flagged).** Kalshi exposes no direct dollar-amount field; the
  dashboard ranks by `volume_24h` and shows an estimated dollar volume, clearly labeled.
- **Demo API key (one-time setup).** Portfolio and trading features require a Kalshi demo API
  key, entered once in the site settings and stored in the browser. Public market data needs no
  key.

## Deliverables

- **Live site (GitHub Pages):** clean landing page plus category subpages — Dashboard,
  Portfolio, Suggestions, Flagged for Review, Sources. All entries/findings are presented as
  simple tables; every table row that states a fact links to an official source, and
  unverified values are flagged.
- **Documentation:** this summary, the verified API reference, the questions/gaps matrix, the
  suggestions list, and a verification log.

## Verification approach

Every API fact in this project was checked against the **official Kalshi Python SDK**
(`kalshi-python` 2.1.4) downloaded from PyPI. Endpoint paths, query parameters, enum values,
and model field names were read directly from the SDK source. No value was inferred or filled
in. See [`VERIFICATION_LOG.md`](VERIFICATION_LOG.md) for the line-by-line record.
