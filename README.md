# KalshiDash3

Live Kalshi **demo** dashboard: highest-dollar events in **Gas Prices, Elections, Culture, Crypto, Golf** — tracked until resolution (yes/no), with price charts, liquidity, paper-trading performance, strategies, suggestions, and open questions.

> **Integration note (2026-11-20):** Two parallel sessions built this repo. The live GitHub Pages site is the `docs/` implementation (merged to `main` via PR #1). This branch (`arena/1c0d1fc0-kalshidash3`) adds a second root-level implementation (`index.html`, `dashboard.html`, `gas.html`, …) plus `data/verified_facts.json`, `EXECUTIVE_SUMMARY.md`, and `scripts/kalshi_tracker.py`. Both fetch live data from the official demo API; neither hardcodes market values. See `COORDINATION.md` for the merge log and `INTEGRATION.md` for the recommended next step (pick one implementation as canonical).

- **Site (GitHub Pages):** `docs/` — landing + subpages by category. Open `docs/index.html` locally or via Pages.
- **Live data:** browser fetches `https://external-api.demo.kalshi.co/trade-api/v2` directly (public endpoints need no key). Docs: https://docs.kalshi.com/getting_started/demo_env
- **Trading:** paper ledger in-browser + `scripts/kalshi_client.py` executor (needs `KALSHI_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` env vars; never commit keys).
- **Coordination:** see `COORDINATION.md`. **Verification:** `docs/verification.html`. **Flagged items:** `docs/flagged.html`.

## Quick start
```bash
python3 scripts/kalshi_client.py scan        # public scan, no keys
# or just open docs/dashboard.html in a browser
```

## Pages
| Page | Purpose |
|---|---|
| `docs/index.html` | Landing |
| `docs/executive-summary.html` | Executive summary |
| `docs/dashboard.html` | Live dashboard (charts, liquidity, resolution) |
| `docs/portfolio.html` | Portfolio + trade execution + categorization |
| `docs/strategies.html` | Strategy hypotheses |
| `docs/suggestions.html` | Improvement proposals (pick a path) |
| `docs/questions.html` | Open questions + discovery plan |
| `docs/verification.html` | Line-by-line verification |
| `docs/flagged.html` | Flagged for Review |
| `docs/sources.html` | Official sources |
