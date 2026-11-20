# Executive Summary — Kalshi Dashboard (Demo)

**Date:** 2026-11-20 · **Scope:** Gas prices, Elections, Culture, Crypto, Golf only · **Environment:** Kalshi demo (`https://external-api.demo.kalshi.co/trade-api/v2`)

## What this project is

A static GitHub Pages site that tracks the highest-dollar live Kalshi demo events in five categories, follows each tracked market until it resolves **yes** or **no**, visualizes price over time (seconds / minutes / hours) and order-book liquidity, and — when the user connects their own demo API key in the browser — tracks demo portfolio performance, executes demo trades, and analyzes fills by category and strategy.

## Official endpoints (verified)

| Surface | Recommended (demo) | Also supported | Source |
|---|---|---|---|
| REST Trade API | `https://external-api.demo.kalshi.co/trade-api/v2` | `https://demo-api.kalshi.co/trade-api/v2` | [Demo env](https://docs.kalshi.com/getting_started/demo_env) |
| WebSocket API | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [Demo env](https://docs.kalshi.com/getting_started/demo_env) |
| Production REST | `https://external-api.kalshi.com/trade-api/v2` | `https://api.elections.kalshi.com/trade-api/v2` | [Environments](https://docs.kalshi.com/getting_started/api_environments) |

Public market data needs no key; trading/portfolio/WebSocket need a signed demo key. Signing = `timestamp + METHOD + path` (no query string). See [Environments](https://docs.kalshi.com/getting_started/api_environments).

## How "highest dollar amount" is defined

Each contract pays $1 if its side wins, so **notional dollars ≈ lifetime volume (contracts) × $1**. The dashboard ranks by `volume_fp` (fallback `volume`), tie-breaks by `open_interest`, and shows both plus 24h volume and close time. This is a ranking heuristic, not a Kalshi-published "dollar volume" field — flagged for review (see `sources.html`).

## Lifecycle tracking

Markets move `initialized → active → closed → determined → finalized`. The dashboard polls `GET /markets?status=open` (maps to `active`) and records `result` (`yes`/`no`/`scalar`) when set; settlement pays $1 per winning contract with zero fee for simple yes/no. Tracked markets persist in browser `localStorage` and appear on the Resolved page. Sources: [Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle.md), [Settlement](https://docs.kalshi.com/getting_started/market_settlement.md).

## Price + liquidity

- **Graph:** X = time, Y = contract price ($). Windows: seconds (live samples), minutes/hours (candlesticks `period_interval` 1/60). Source: [Candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks.md).
- **Liquidity:** `GET /markets/{ticker}/orderbook` returns **bids only** (`yes_dollars`, `no_dollars`); asks are implied as $1 − opposite bid. Each level shows contracts available at that price. Source: [Orderbook](https://docs.kalshi.com/getting_started/orderbook_responses.md).

## Portfolio & trading (demo account)

With a user-supplied demo key (browser `localStorage` only, never committed), the Portfolio page reads balance, positions, fills, and settlements; categorizes fills by category/side/taker; computes win rate and P&L; and places demo orders via `POST /portfolio/events/orders`. A Python script (`scripts/kalshi_tracker.py`) does the same headlessly with env-var keys. **No credentials were provided for this session, so end-to-end trading could not be exercised here** — see Questions Q1–Q4 on `suggestions.html`.

## Key caveats

1. Demo prices "may not be reflective of those in real markets" — rankings are illustrative. ([Demo env](https://docs.kalshi.com/getting_started/demo_env))
2. No live values are hardcoded; every number on the site is fetched live in the browser. Static claims are in `data/verified_facts.json` with source links; anything unconfirmed is blank + flagged.
3. This sandbox cannot reach Kalshi hosts directly, so live response shapes are implemented defensively (fixed-point `*_dollars`/`*_fp` fields with legacy cent fallbacks).

## Where to go next

- **Dashboard:** `dashboard.html` · **Categories:** `gas.html`, `elections.html`, `culture.html`, `crypto.html`, `golf.html` · **Resolved:** `resolved.html` · **Portfolio:** `portfolio.html` · **Suggestions + Questions:** `suggestions.html` · **Sources/Flagged:** `sources.html`
