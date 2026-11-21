# KalshiDash3

A source-linked dashboard for the **Kalshi demo** environment, limited to five topics:
**Gas Prices, Elections, Culture, Crypto and Golf**.

**Live site:** https://kanlerxz87-cyber.github.io/KalshiDash3/

Every market number on the site is produced by a scheduled, credential-free collector that reads the official
demo Trade API and commits a timestamped snapshot. On top of that snapshot layer, the browser can poll the same
public demo API directly (with a CORS self-test and automatic fallback), so the alert chats and dashboard tick in
near-real time. Nothing is typed by hand, and anything that cannot be confirmed against an official Kalshi page is
left blank and listed on the *Flagged for Review* page.

---

## What the site contains

| Page | What it answers |
|---|---|
| `index.html` | Landing page, snapshot age, largest live market per category |
| `executive-summary.html` | Requirement-by-requirement status, the four facts a decision-maker needs |
| `categories.html` + `gas / elections / culture / crypto / golf.html` | One page per topic, nothing mixed across topics |
| `dashboard.html` | Price chart (X = time, Y = contract price): official candles at 1/60/1440 minutes plus the collector's observations, archived ≥ $0.10 swings marked and deep-linkable, liquidity ladder, resolution tracker, optional in-browser live polling |
| `alerts.html` | Two scrolling alert chats — every ≥ $0.10 swing in either direction, plus the model-picks (high-ROI screen) feed; each alert links to the exact API query, the order book and news-search leads |
| `trading.html` | Auto-sim engine: automated paper trades on three disclosed strategies, settled from the API's literal `result`, with performance by strategy / topic / price band / exit reason |
| `portfolio.html` | Real demo-account endpoints, the working executor, and a labelled paper ledger with fee modelling |
| `strategies.html` | Trade categorisation and four strategy hypotheses with the evidence each still needs |
| `simulation.html` | Paper-only results of four fixed rules on the ≥ $0.10 swing archive: fills, fees, settlements, results by strategy, topic and trade type |
| `suggestions.html` | Eighteen proposals; each with its effort, risk and success metric |
| `questions.html` | Nine questions: known / unknown / best answer if forced / how to close it |
| `verification.html` | 59 claims, each with the official page it was checked against |
| `flagged.html` | 38 irregularities found, plus every value deliberately left blank |
| `sources.html` | The complete source list |

## Repository layout

```
*.html                the published site — one page per topic, shared shell in assets/
assets/               site.css + site.js (no build step, no dependencies)
data/categories.json  the five topics and their confirmed seed series
data/verified_facts.json  every static claim + its official source
data/findings.json    questions, suggestions, flagged irregularities
data/live/            collected snapshots (written by scripts/collect.py)
scripts/collect.py    credential-free demo data collector
scripts/build_alerts.py   builds the persistent ≥ $0.10 swing archive data/live/alerts_archive.json and data/live/alerts.json; rules in data/alert_rules.json
scripts/simulate.py       paper-only simulator: fixed rules in data/strategies.json applied to the alert archive; writes data/live/simulation.json (no orders, no account)
scripts/tests/test_simulate.py  fee-table, settlement and signal tests for the simulator (synthetic fixtures)
scripts/kalshi_client.py  demo trade executor (env-var credentials only)
scripts/check_site.py     link / HTML / data check, run before deploy
scripts/tests/validate_live.py  refuses a fabricated snapshot
scripts/tests/validate_alerts.py  provenance: re-derives every alert from the committed observations and reproduces the feeds from the archive + rules
scripts/tests/test_collect_coverage.py  offline: the scan uses the documented mve_filter, and price history is never pruned for a market an alert cites
scripts/tests/test_pages_dom.js  jsdom render tests, including the chart (candle request shape, no fake 0c) and the alert→chart deep link
.github/workflows/collect.yml   scheduled collection
.github/workflows/pages.yml     deploy to Pages (same files the branch publisher serves)
```

## Release verification

The Pages workflow runs on pull requests and again before deployment. It stages only
HTML, `assets/`, and `data/` — not repository scripts, test dependencies or coordination logs.
GitHub Pages must use **GitHub Actions**, not legacy branch publishing, for this gate to apply.

```bash
npm install --no-save --package-lock=false jsdom@26  # test-only; Node 20+ required
python3 scripts/verify_release.py
```

This single offline command checks Python, shared and inline browser-script syntax;
all committed-data validators; alert, fee, ROI and simulation regressions; engine and
DOM behavior; and internal links across the 21 pages. Missing Node or jsdom is a failure,
not a silent skip. It does not fetch fresh prices, verify external URL availability,
certify profitability, or authenticate a demo account. Official endpoint and authentication
references: [demo environment](https://docs.kalshi.com/getting_started/demo_env) and
[WebSocket quick start](https://docs.kalshi.com/getting_started/quick_start_websockets).

## How to re-run everything

Public collection and offline verification need no Kalshi credentials. Account access and
order execution do require demo credentials. Market snapshots come from public demo endpoints.

```bash
python3 scripts/collect.py            # writes data/live/markets.json + price_history.json
python3 scripts/build_alerts.py       # writes data/live/alerts_archive.json + alerts.json
python3 scripts/simulate.py           # writes data/live/simulation.json (paper only)
python3 scripts/tests/validate_live.py
python3 scripts/tests/validate_alerts.py
python3 scripts/tests/test_alerts.py
python3 scripts/tests/test_simulate.py
python3 scripts/check_site.py
python3 -m http.server 8000           # then open http://localhost:8000
```

## Track the real demo portfolio (the one manual step)

Kalshi demo accounts must be created by a person, and Kalshi states the demo account
[does not come with funds preloaded](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account).
Until that happens, no balance exists to report and this project leaves the value blank rather than inventing one.

1. Sign up at <https://demo.kalshi.co/sign-up> and add mock funds.
2. Create an API key under *Account Settings → API Keys* and save the private key PEM.
3. Export it locally — never commit it:

```bash
export KALSHI_KEY_ID=...
export KALSHI_PRIVATE_KEY_PATH=/absolute/path/to/kalshi.key
python3 scripts/kalshi_client.py balance
python3 scripts/kalshi_client.py positions
python3 scripts/kalshi_client.py buy MARKET-TICKER 25 0.42
```

The executor refuses to talk to a non-demo base URL unless `KALSHI_ALLOW_PRODUCTION=1` is set, and it posts to
`POST /portfolio/events/orders` because the legacy `/portfolio/orders` write endpoints now return `410 Gone`.

## Rules this repository follows

1. **No invented values.** A value that is not in an API response or an official document is blank, and blank is flagged.
2. **No inferred tickers.** A series is "confirmed" only if it appears verbatim in the official fee schedule;
   everything else is labelled `keyword` and flagged.
3. **Results are never coerced.** `result` may be `yes`, `no`, `scalar` or empty, and is displayed exactly as returned.
4. **Provenance on every row.** Each row carries the query URL and each snapshot carries its fetch time.
5. **Demo is labelled demo.** Kalshi warns demo prices may not reflect real markets.

## Known limitations

- The collector cannot run in the environment that built this repository (no network route to Kalshi), so collection
  runs on GitHub Actions. Scheduled workflows can be delayed or skipped; the site shows the snapshot age for that reason.
- In-browser live polling depends on CORS headers the demo API returns but Kalshi does not document. The engine probes
  the API at runtime, records the observed headers per collector run into `data/live/cors.json`, and falls back to
  committed snapshots automatically (flagged as F-14).
- Unauthenticated request limits are undocumented; the poller is conservative (default 10 s, back-off on 429).
- Seconds-resolution price history cannot be requested from Kalshi — candlesticks support 1, 60 and 1440 minute
  intervals only — so it is accumulated one observation per collector run (plus live poll points in the browser session).
- WebSocket streaming requires an API key at the handshake, so a static site cannot stream ticks.
- Portfolio performance and the auto-sim engine are labelled paper simulations until demo credentials exist.
  Kalshi states a demo account "does not come with funds preloaded" and must be created by a person.
- Paper results need a stored bid and ask at the alert time. New archive entries now carry `to_yes_bid` /
  `to_yes_ask` (request R-2, implemented 2026-11-20); entries written before that still have no quote and
  stay unfilled, as do quotes whose spread exceeds the 0.10 cap (Flagged F-19, F-23).
- Paper results on demo prices are not evidence that a strategy would make money in real markets (Kalshi: demo prices may not reflect real markets).

## Sources

All documentation used, with links, is listed on the [Sources page](https://kanlerxz87-cyber.github.io/KalshiDash3/sources.html)
and in the repository's `COORDINATION.md`. The primary ones are
[docs.kalshi.com](https://docs.kalshi.com/welcome),
the [demo environment page](https://docs.kalshi.com/getting_started/demo_env) and the
[fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf).

