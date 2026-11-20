# KalshiDash3 — Live Kalshi Demo Dashboard

Tracks the highest-dollar live Kalshi demo events in **gas prices, elections, culture, crypto, and golf only**, follows each tracked market until it resolves **yes/no**, charts price over time (seconds/minutes/hours) with order-book liquidity, and — with your own demo key — tracks portfolio performance, executes demo trades, and analyzes fills by category/strategy.

**Live site:** https://kanlerxz87-cyber.github.io/KalshiDash3/ (after Pages deploy)

## Official endpoints (verified)

| Surface | Recommended (demo) | Also supported | Source |
|---|---|---|---|
| REST | `https://external-api.demo.kalshi.co/trade-api/v2` | `https://demo-api.kalshi.co/trade-api/v2` | [Demo env](https://docs.kalshi.com/getting_started/demo_env) |
| WebSocket | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` | `wss://demo-api.kalshi.co/trade-api/ws/v2` | [Demo env](https://docs.kalshi.com/getting_started/demo_env) |

Production: `https://external-api.kalshi.com/trade-api/v2` — [Environments](https://docs.kalshi.com/getting_started/api_environments). Public market data needs no key; trading/portfolio need a signed demo key.

## Pages

- `index.html` — landing + top 5
- `dashboard.html` — live ranking, price graph, liquidity, track-until-resolved
- `gas.html` / `elections.html` / `culture.html` / `crypto.html` / `golf.html` — category subpages
- `resolved.html` — yes/no resolutions
- `portfolio.html` — demo balance/positions/fills/settlements + trade form + analysis
- `suggestions.html` — improvement proposals + Questions/Info/Answers
- `sources.html` — verified facts + Flagged for Review

## Run

Static site — open `index.html` via any static server (e.g. `python3 -m http.server`). Live data is fetched in the browser from the demo API.

Headless tracker/trader (needs `cryptography` + demo key env vars):

```bash
pip install cryptography
python3 scripts/kalshi_tracker.py --rank
KALSHI_API_KEY_ID=... KALSHI_PRIVATE_KEY_PATH=./demo.key python3 scripts/kalshi_tracker.py --balance
```

## Verification

- Static claims: `data/verified_facts.json` (each row links to an official source; unconfirmed = blank + unverified).
- Live values: never hardcoded; fetched client-side.
- Executive summary: `EXECUTIVE_SUMMARY.md`. Coordination: `COORDINATION.md`.

> Demo warning: demo prices “may not be reflective of those in real markets.” See [demo_env](https://docs.kalshi.com/getting_started/demo_env).
