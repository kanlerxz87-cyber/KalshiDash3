# Executive summary — Kalshi demo dashboard (snapshot 2026-11-20 UTC)

**Live site:** https://kanlerxz87-cyber.github.io/KalshiDash3/docs/9b246e37/ (GitHub Pages, legacy build from `main` `/`; folder `docs/9b246e37/`)
**Data source:** Kalshi DEMO Trade API, `https://external-api.demo.kalshi.co/trade-api/v2` (recommended demo endpoint in the [demo environment docs](https://docs.kalshi.com/getting_started/demo_env.md)).

## 1. What was built
- A static dashboard with a landing page, one subpage per category (gas prices, elections, culture, crypto, golf), a live price chart with a liquidity table, a portfolio page (blocked, see §4), analysis, questions, suggestions, a **Flagged for Review** page, and a sources log.
- Every table row carries a link to its official source (Kalshi API response, Kalshi terms PDF, AAA page). Missing values are shown as "— unverified", never filled in.
- 30 tracked rows (12 gas rungs, 10 crypto series, 4 election series, 2 culture series, 2 golf rows) and 3 resolved demo test markets.

## 2. Key findings (verified against the sources listed on the Sources page)
- **Exchange:** the demo exchange reports `trading_active: true` ([status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status)).
- **Gas:** AAA's national regular average was **$3.6898 on 11/20/26**, down from $4.2786 a month earlier ([AAA](https://gasprices.aaa.com/)). Gas rungs settle on AAA's figure ([rules](https://external-api.demo.kalshi.co/trade-api/v2/events?series_ticker=KXAAAGASM&status=open&with_nested_markets=true&limit=2)). In the demo ladder for Nov 30, 2026, the $2.50–$2.90 rungs quote 0.01 with no bid; $3.00–$3.40 quote 0.97–0.98; the $3.50 rung has the largest volume (6,828 contracts) and a 0.50 / 0.51 top of book. The demo quote for $3.50 is not explained by the data (open question Q-05).
- **Crypto:** the largest series by contracts traded are KXLINK (24,510,512), KXBTCMINY (19,464,180), and KXAVAX (17,532,299). These are series totals in contracts, not dollars ([series list](https://external-api.demo.kalshi.co/trade-api/v2/series?category=Crypto&include_volume=true)).
- **Elections, culture, golf:** little or no volume (4 election series total 41 contracts; both culture series 0.00; the golf series 0.00).
- **Resolution:** settled markets return `result: yes|no` and `status: finalized`. Only demo test markets have resolved in the sample ([settled markets](https://external-api.demo.kalshi.co/trade-api/v2/markets?status=settled&limit=3)). No real market in the five topics has resolved in this snapshot.

## 3. Irregularities flagged for your review (full list on the site)
- Demo prices may not match real markets (F-01, [docs](https://docs.kalshi.com/getting_started/demo_env.md)).
- Culture settlement-source lists include placeholders and unrelated sites (F-05).
- KXDOGEPERP has no settlement source or contract (F-08).
- Many series point their `contract_url` at a staging S3 host (F-06).
- Orderbooks and candles are empty for most markets, so liquidity can only be shown for a few (F-03).
- Some timestamps are older than the events they belong to (F-04).
- "Highest dollar amount" cannot be computed from the fields returned: `volume_fp` is contracts traded (F-11).

## 4. What is blocked, and why
- **Portfolio, trades, P&L, and strategy results are not available.** Portfolio and order endpoints require signed requests with a demo API key ([auth docs](https://docs.kalshi.com/getting_started/quick_start_authenticated_requests.md)). No key exists in this sandbox, and the agent cannot create a Kalshi account or key. **No trades were placed and no P&L is shown.** Providing a demo key as a repository secret unblocks this (suggestion S-02).

## 5. Decisions needed from you (suggestions page, nothing implemented yet)
1. Pick the metric for "highest dollar amount" (S-04).
2. Approve creating a Kalshi demo API key and storing it as a secret (S-02).
3. Approve an hourly data-refresh job (S-01). It has not been run from GitHub yet.
4. Choose whether the strategy taxonomy waits for demo trades (S-07).

## 6. Limits of this work
- The sandbox could not reach the Kalshi host directly (SSL error), so all Kalshi values come from fetch results of the official API, copied field by field.
- The category lists are partial: the Elections list alone has 529 result pages (F-17).
- Browser access to the demo API (CORS) from GitHub Pages is untested (F-16). If blocked, the live chart says so.
- Nothing here is investment advice.
