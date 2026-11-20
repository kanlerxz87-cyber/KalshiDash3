# Coordination Board — KalshiDash3

Session ID: `session-1c0d1fc0` (branch `arena/1c0d1fc0-kalshidash3`)
Base commit: `49ba7bce3112e9e0b4c7534af961e1d0ef8d19ff` (main)
Started: 2026-11-20

> Single active session. All tasks below are claimed by `session-1c0d1fc0`.
> Scopes are non-overlapping by file. No other session has claimed work.

## Task board

| ID | Task | Status | Owner | Files touched |
|----|------|--------|-------|---------------|
| T1 | Repo review + executive summary + verified facts dataset | in progress | session-1c0d1fc0 | `README.md`, `data/verified_facts.json`, `EXECUTIVE_SUMMARY.md` |
| T2 | Live dashboard (highest-dollar events, 5 categories, price graph, liquidity) | in progress | session-1c0d1fc0 | `index.html`, `dashboard.html`, `assets/css/style.css`, `assets/js/kalshi.js`, `assets/js/dashboard.js`, `assets/js/charts.js` |
| T3 | Category subpages (gas, elections, culture, crypto, golf) + resolved tracker | in progress | session-1c0d1fc0 | `gas.html`, `elections.html`, `culture.html`, `crypto.html`, `golf.html`, `resolved.html`, `assets/js/category.js` |
| T4 | Portfolio + trading + trade analysis/strategies (demo account) | in progress | session-1c0d1fc0 | `portfolio.html`, `assets/js/portfolio.js`, `scripts/kalshi_tracker.py` |
| T5 | Suggestions + Questions/Info/Answers + Sources/Flagged-for-Review | in progress | session-1c0d1fc0 | `suggestions.html`, `sources.html` |
| T6 | GitHub Pages deploy + final integration, PR to main, merge | unclaimed | session-1c0d1fc0 (integration) | `.github/workflows/pages.yml`, `COORDINATION.md` |

## Verification log

- Demo endpoints verified 2026-11-20 against official docs:
  - https://docs.kalshi.com/getting_started/demo_env
  - https://docs.kalshi.com/getting_started/api_environments
- Market lifecycle / settlement / orderbook verified against:
  - https://docs.kalshi.com/getting_started/market_lifecycle.md
  - https://docs.kalshi.com/getting_started/market_settlement.md
  - https://docs.kalshi.com/getting_started/orderbook_responses.md
- Sandbox cannot reach `*.kalshi.co` / `*.kalshi.com` directly (egress allowlist is github/npm/pypi only); live data is fetched client-side in the browser from the official demo base URL. No live values are hardcoded in the repo.
- No demo API keys are stored in the repo. Portfolio/trading requires the user to paste their own demo key ID + PEM in the browser (localStorage only) or via env vars for the Python script.

## Irregularities / flagged for review

- F1: Kalshi demo market prices/behavior "may not be reflective of those in real markets" (official demo_env page). Demo rankings are therefore illustrative, not production signals.
- F2: Orderbook returns bids only (yes/no); asks are implied as $1 − opposite bid. Dashboard labels this explicitly.
- F3: `GET /markets?status=open` maps to internal status `active`; `settled` maps to `finalized`. Dashboard polls both.
- F4: Sandbox egress blocks direct Kalshi API calls, so live verification of response shapes must be done in-browser; shapes follow official OpenAPI/docs field names (`yes_bid_dollars`, `volume_fp`, `orderbook_fp`, etc.) with defensive fallbacks for legacy cent fields.
- F5: No demo account credentials were provided, so portfolio/trading is implemented but cannot be exercised end-to-end in this session. See Questions page Q1–Q4.

## Handoff / conflict log

- 2026-11-20: session-1c0d1fc0 created this board and claimed T1–T5. T6 will be claimed at integration time.
