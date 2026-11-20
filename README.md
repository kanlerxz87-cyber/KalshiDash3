# KalshiDash3

A source-linked dashboard for the **Kalshi demo** environment, limited to five topics:
**Gas Prices, Elections, Culture, Crypto and Golf**.

**Live site:** https://kanlerxz87-cyber.github.io/KalshiDash3/

Every market number on the site is produced by a scheduled, credential-free collector that reads the official
demo Trade API and commits a timestamped snapshot. Nothing is typed by hand, and anything that cannot be
confirmed against an official Kalshi page is left blank and listed on the *Flagged for Review* page.

---

## What the site contains

| Page | What it answers |
|---|---|
| `docs/index.html` | Landing page, snapshot age, largest live market per category |
| `docs/executive-summary.html` | Requirement-by-requirement status, the four facts a decision-maker needs |
| `docs/categories.html` + `gas / elections / culture / crypto / golf.html` | One page per topic, nothing mixed across topics |
| `docs/dashboard.html` | Price chart (X = time, Y = contract price) with seconds/minutes/hours windows, liquidity ladder, resolution tracker |
| `docs/portfolio.html` | Real demo-account endpoints, the working executor, and a labelled paper ledger with fee modelling |
| `docs/strategies.html` | Trade categorisation and four strategy hypotheses with the evidence each still needs |
| `docs/suggestions.html` | Eight proposals; four shipped to remove a correctness risk, four awaiting your decision |
| `docs/questions.html` | Eight questions: known / unknown / best answer if forced / how to close it |
| `docs/verification.html` | 44 claims, each with the official page it was checked against |
| `docs/flagged.html` | Nine irregularities found, plus every value deliberately left blank |
| `docs/sources.html` | The complete source list |

## Repository layout

```
docs/                 the published site (GitHub Pages artifact)
docs/data/categories.json  the five topics and their confirmed seed series
docs/data/verified_facts.json  every static claim + its official source
docs/data/findings.json    questions, suggestions, flagged irregularities
docs/data/live/            collected snapshots (written by scripts/collect.py)
scripts/collect.py    credential-free demo data collector
scripts/kalshi_client.py  demo trade executor (env-var credentials only)
scripts/check_site.py     link / HTML / data check, run before deploy
scripts/tests/validate_live.py  refuses a fabricated snapshot
.github/workflows/collect.yml   scheduled collection
.github/workflows/pages.yml     deploy docs/ to Pages
```

## How to re-run everything

Nothing here needs credentials. All market data comes from public demo endpoints.

```bash
python3 scripts/collect.py            # writes docs/data/live/markets.json + price_history.json
python3 scripts/tests/validate_live.py
python3 scripts/check_site.py
python3 -m http.server -d docs 8000   # then open http://localhost:8000
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
- Seconds-resolution price history cannot be requested from Kalshi — candlesticks support 1, 60 and 1440 minute
  intervals only — so it is accumulated one observation per collector run.
- WebSocket streaming requires an API key at the handshake, so a static site cannot stream ticks.
- Portfolio performance is a labelled paper simulation until demo credentials exist.

## Sources

All documentation used, with links, is listed on the [Sources page](https://kanlerxz87-cyber.github.io/KalshiDash3/sources.html)
and in the repository's `COORDINATION.md`. The primary ones are
[docs.kalshi.com](https://docs.kalshi.com/welcome),
the [demo environment page](https://docs.kalshi.com/getting_started/demo_env) and the
[fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf).

## Session 9b246e37: verified dashboard subsite (`docs/9b246e37/`)

- **Page:** https://kanlerxz87-cyber.github.io/KalshiDash3/docs/9b246e37/
- Pages: overview, category tables (gas, elections, culture, crypto, golf), live chart and liquidity from the public demo endpoints, portfolio (blocked: no demo API key), analysis, questions, suggestions (nothing implemented), flagged, sources.
- Data: `docs/9b246e37/data/dashboard.json`. Values copied from Kalshi DEMO API responses fetched 2026-11-20 UTC, each row with its source URL. Blanks are unverified.
- Details and the post-merge record are in `COORDINATION.md`.
