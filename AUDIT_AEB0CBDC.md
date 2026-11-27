# Independent Live-API & Lifecycle Verification Audit — Session `arena-aeb0cbdc` (2026-11-27)

**Session:** `arena-aeb0cbdc`  
**Branch:** `arena/aeb0cbdc-kalshidash3` (base `95cc0ae` on `main`, collector snapshot `2026-11-27T22:20:02Z`)  
**Live GitHub Pages site:** <https://kanlerxz87-cyber.github.io/KalshiDash3/>  
**Executive summary:** <https://kanlerxz87-cyber.github.io/KalshiDash3/executive-summary.html>  
**Flagged for review:** <https://kanlerxz87-cyber.github.io/KalshiDash3/flagged.html>

---

## 1. Executive Summary of Audit & Findings

This audit independently verified the shipped 21-page Kalshi demo dashboard, its committed collector artifacts (`2026-11-27T22:20:02Z`), and live official Kalshi Demo Trade API and documentation endpoints line by line on 2026-11-27.

1. **Both Demo API Hosts & Documentation Verified Live:**
   - Recommended REST root [`https://external-api.demo.kalshi.co/trade-api/v2/exchange/status`](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) and supported alias [`https://demo-api.kalshi.co/trade-api/v2/exchange/status`](https://demo-api.kalshi.co/trade-api/v2/exchange/status) both returned `exchange_active: true` and `trading_active: true` across all 4 demo shards.
   - Official documentation at [`docs.kalshi.com/getting_started/demo_env`](https://docs.kalshi.com/getting_started/demo_env) and [`docs.kalshi.com/getting_started/quick_start_websockets`](https://docs.kalshi.com/getting_started/quick_start_websockets) confirms both REST roots and both WebSocket roots (`wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` and `wss://demo-api.kalshi.co/trade-api/ws/v2`), mock-fund separation from production, the warning that demo prices may not reflect real markets, and mandatory authentication on the WebSocket handshake even for public channels.
2. **All Five Topic Headlines & Liquidity Depth Verified Against Live Demo API:**
   - Every headline market rendered on [`index.html`](https://kanlerxz87-cyber.github.io/KalshiDash3/index.html) across the five scoped categories (**Gas Prices**, **Elections**, **Culture**, **Crypto**, **Golf**) was fetched directly from `GET /markets/{ticker}` and matched the committed snapshot (`2026-11-27T22:20:02Z`), with expected minor live trading volume progression (+86.21 contracts) on the active DP World Tour golf market.
   - Live orderbook fetch for `KXDPWORLDTOUR-BMAPC26-HBAR` confirmed Kalshi's reciprocal bid-only `orderbook_fp` structure (`best NO bid $0.9310` → implied `best YES ask $0.0690`), matching [`docs.kalshi.com/getting_started/orderbook_responses`](https://docs.kalshi.com/getting_started/orderbook_responses).
3. **Out-of-Window Alert Lifecycle Follow-Up Confirmed Live in Production (Closing F-113's Operational Gap):**
   - Earlier session `arena-035cd7c0` flagged (`F-113`) that out-of-window alerted contracts such as `KXPGATOUR-THRC26-BHAR` (The RSM Classic) showed `"not in snapshot"` until `C440-LIFECYCLE` ran in production.
   - Verified in the `2026-11-27T22:20:02Z` snapshot (`data/live/markets.json` → `alert_lifecycle.rows`, 50 tracked tickers) AND on the live served [`alerts.html`](https://kanlerxz87-cyber.github.io/KalshiDash3/alerts.html): `KXPGATOUR-THRC26-BHAR`, `KXPGATOUR-THRC26-MTHO`, `KXPGATOUR-THRC26-RHOJ`, `KXPGATOUR-THRC26-MGRE`, and `KXAAAGASD-26NOV21-3.6600` are now tracked to `status: "finalized"`, `result: "no"`, matching the live official `GET /markets/{ticker}` responses byte-for-byte on `result`, `settlement_ts`, and `settlement_value_dollars`.
4. **Full Offline Release Gate & Provenance Audits:**
   - `python3 scripts/verify_release.py` — **PASS** (all Python/JS syntax checks, `validate_live.py`, `validate_alerts.py`, `validate_catalysts.py`, `validate_roi.py`, unit suites, 13 Node/jsdom render & numeric-recomputation suites including `audit_rendered_numbers.js` and `test_staleness_disclosure.js`, and `check_site.py` across all 21 HTML pages).
   - `python3 scripts/audit_sources.py` — **PASS** (614 open markets, 200 settled markets, 592 series records, 20 orderbooks, 164 all-event alerts, 124 high-ROI model alerts, 184 archived alerts, 69 paper positions, 72 verified facts, 1 deliberately blank unverified fact `C-20`).

---

## 2. Line-by-Line Live Official API Verification (2026-11-27 ~22:30–22:36Z)

| Topic / Check | Ticker / Endpoint | Snapshot Value (`22:20:02Z`) | Live Official API Value (`22:31Z`) | Status & Official Source Link |
|---|---|---|---|---|
| Exchange status (primary) | `GET /exchange/status` | Demo active | `exchange_active: true`, `trading_active: true` (4 shards) | Verified · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |
| Exchange status (alias) | `GET /exchange/status` | Demo active | `exchange_active: true`, `trading_active: true` (4 shards) | Verified · [Official API](https://demo-api.kalshi.co/trade-api/v2/exchange/status) |
| **Gas Prices** headline | `KXAAAGASM-26NOV30-3.90` | `last: $0.7500`, `vol: 31,027.52`, `oi: 24,988.65`, est. `$23,271` | `last_price_dollars: "0.7500"`, `volume_fp: "31027.52"`, `open_interest_fp: "24988.65"`, `status: "active"` | Exact match · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASM-26NOV30-3.90) |
| **Elections** headline | `KXPRESNOMD-28-GPLA` | `last: $0.9900`, `vol: 465,856,531.27`, `oi: 44,108,150.17`, est. `$461,197,966` | `last_price_dollars: "0.9900"`, `volume_fp: "465856531.27"`, `open_interest_fp: "44108150.17"`, `status: "active"` | Exact match · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPRESNOMD-28-GPLA) |
| **Culture** headline | `KXOSCARPIC-27-YOU` | `last: $0.2400`, `vol: 1,368,307.31`, `oi: 924,352.88`, est. `$328,394` | `last_price_dollars: "0.2400"`, `volume_fp: "1368307.31"`, `open_interest_fp: "924352.88"`, `status: "active"` | Exact match · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXOSCARPIC-27-YOU) |
| **Crypto** headline | `KXETHY-27JAN0100-T4999.99` | `last: $0.9000`, `vol: 18,263,278.14`, `oi: 1,382,157.55`, est. `$16,436,950` | `last_price_dollars: "0.9000"`, `volume_fp: "18263278.14"`, `open_interest_fp: "1382157.55"`, `status: "active"` | Exact match · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXETHY-27JAN0100-T4999.99) |
| **Golf** headline | `KXDPWORLDTOUR-BMAPC26-HBAR` | `last: $0.0690`, `vol: 341,498.46`, `oi: 320,490.87`, est. `$23,563` | `last_price_dollars: "0.0690"`, `volume_fp: "341584.67"` (+86.21 live trades), `open_interest_fp: "320490.87"`, `status: "active"` | Consistent (live trades) · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDPWORLDTOUR-BMAPC26-HBAR) |
| **Golf** liquidity ladder | `KXDPWORLDTOUR-BMAPC26-HBAR/orderbook` | Implied YES ask from `1 - best NO bid` | `yes_dollars` best `$0.0550 × 6059.60`; `no_dollars` best `$0.9310 × 388.53` → implied YES ask `$0.0690` | Verified · [Official Orderbook](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXDPWORLDTOUR-BMAPC26-HBAR/orderbook) |
| Lifecycle follow-up (Golf) | `KXPGATOUR-THRC26-BHAR` | `alert_lifecycle`: `finalized`, `result: "no"`, `settlement_ts: 2026-11-23T19:58:03.108438Z` | `status: "finalized"`, `result: "no"`, `settlement_ts: "2026-11-23T19:58:03.108438Z"`, `settlement_value_dollars: "0.0000"` | Exact match · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXPGATOUR-THRC26-BHAR) |
| Lifecycle follow-up (Gas) | `KXAAAGASD-26NOV21-3.6600` | `alert_lifecycle`: `finalized`, `result: "no"`, `settlement_ts: 2026-11-21T13:11:17.960569Z` | `status: "finalized"`, `result: "no"`, `settlement_ts: "2026-11-21T13:11:17.960569Z"`, `settlement_value_dollars: "0.0000"` | Exact match · [Official API](https://external-api.demo.kalshi.co/trade-api/v2/markets/KXAAAGASD-26NOV21-3.6600) |

---

## 3. Official Documentation & Fee Schedule Re-Verification

Every core technical constraint and formula used by the site was re-checked directly against Kalshi's official documentation on 2026-11-27:

- **Demo Environment & Endpoints:** [`https://docs.kalshi.com/getting_started/demo_env`](https://docs.kalshi.com/getting_started/demo_env) — Confirms REST `https://external-api.demo.kalshi.co/trade-api/v2` (and `https://demo-api.kalshi.co/trade-api/v2`), WebSocket `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (and `wss://demo-api.kalshi.co/trade-api/ws/v2`), mock funds, credential isolation, and non-representative demo pricing.
- **Demo Account Setup & Funding:** [`https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account`](https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account) — Confirms human sign-up at `https://demo.kalshi.co/sign-up` and verbatim statement: *"Your demo account does not come with funds preloaded."*
- **API Keys & Request Signing:** [`https://docs.kalshi.com/getting_started/api_keys`](https://docs.kalshi.com/getting_started/api_keys) — Confirms Ed25519 (RFC 8032) and RSA-PSS SHA-256 over `timestamp_ms + HTTP_METHOD + path_without_query` with 30-second clock tolerance.
- **WebSocket Handshake Auth:** [`https://docs.kalshi.com/getting_started/quick_start_websockets`](https://docs.kalshi.com/getting_started/quick_start_websockets) — Confirms `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, and `KALSHI-ACCESS-TIMESTAMP` are required on handshake even when subscribing to public channels (`ticker`, `trade`, `market_lifecycle_v2`).
- **Candlestick Intervals:** [`https://docs.kalshi.com/api-reference/market/get-market-candlesticks`](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) — Confirms `period_interval` accepts `1` (1 min), `60` (1 hr), or `1440` (1 day) only; sub-minute/seconds series must be accumulated from observations.
- **Orderbook Reciprocal Bids:** [`https://docs.kalshi.com/getting_started/orderbook_responses`](https://docs.kalshi.com/getting_started/orderbook_responses) — Confirms `orderbook_fp` returns ascending `[price_dollars, count_fp]` bid arrays only (`best YES ask = $1.00 - best NO bid`) and HTTP 200 empty arrays for empty or unknown tickers.
- **Market Lifecycle & Settlement:** [`https://docs.kalshi.com/getting_started/market_lifecycle`](https://docs.kalshi.com/getting_started/market_lifecycle) and [`https://docs.kalshi.com/getting_started/market_settlement`](https://docs.kalshi.com/getting_started/market_settlement) — Confirms `determined` precedes payout, `finalized` is terminal settlement, $1.00 payout per winning net contract, and $0 settlement fee on binary yes/no determinations.
- **Create Order V2:** [`https://docs.kalshi.com/api-reference/orders/create-order-v2`](https://docs.kalshi.com/api-reference/orders/create-order-v2) — Confirms `POST /portfolio/events/orders` with `side` (`bid`|`ask`), `count`, and `price` on the demo roots.
- **Fee Schedule (Effective July 7, 2026):** [`https://kalshi.com/docs/kalshi-fee-schedule.pdf`](https://kalshi.com/docs/kalshi-fee-schedule.pdf) — Confirms general taker fee `round up(M × 0.07 × C × P × (1 - P))`, maker fee `round up(M × 0.0175 × C × P × (1 - P))`, zero settlement/membership fees, and Non-Standard Fees multipliers (`M = 0` for `KXBTCY`, `KXETHY`, `KXELECTIRAN`; `M = 1` for `KXAAAGASM`, etc.).

---

## 4. Standing Non-Blocking Items Published on `flagged.html`

All irregularities and unverified items are transparently disclosed on [`flagged.html`](https://kanlerxz87-cyber.github.io/KalshiDash3/flagged.html) (113 items total across `data/findings.json` and `data/release_findings.json`, plus `DEPLOY-1` and blank claim `C-20`):

- **`F-07` (Demo Account Balance & Live Order Execution):** Blank (`unverified`) because no demo account credentials (`KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`) were provided and a static GitHub Pages site cannot safely store private keys. Paper simulation (`simulation.html`, `trading.html`, `portfolio.html`) and the credential-ready V2 CLI (`scripts/kalshi_client.py`) are provided and clearly labelled.
- **`F-14` / `F-26` / `F-77` (High-ROI Model & Experimental Alert Filter):** Both the fee-aware orderbook ROI model (`roi.html`, currently `0` picks after spread + taker fee) and the alert chat's experimental seed+volume filter (`alerts.html`, 124 rows) are disclosed project heuristics on demo data, not guaranteed trading edges.
- **`F-25` / `F-93` (Jump Cause Attribution):** Kalshi provides no causal news API; `cause_link` remains blank rather than hallucinated, while settlement-reference checks (`catalysts.json`) and clearly-labelled search leads are shown separately.
- **`F-111` & `F-112` (Fee Multiplier Source Discrepancy & `KXMAXSHARDINGTEST`):** Disclosed for human review with direct official links (`kalshi-fee-schedule.pdf` vs `GET /series/{ticker}`, and `GET /series/KXMAXSHARDINGTEST`).
- **`DEPLOY-1` (GitHub Pages Legacy Branch Publisher):** Repository Pages `build_type` is `legacy` (`main /`); switching to `GitHub Actions` requires repository administrator UI access (`Settings → Pages`). Both `Deploy site to GitHub Pages` and `pages build and deployment` succeed on `main`.
