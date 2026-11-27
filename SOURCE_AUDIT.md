# Independent source and collector audit — 2026-11-27

Session: `arena-72ae7bca`. This is an audit of the existing dashboard, not a claim
that a new dashboard was built from scratch. The main executive summary remains
[executive-summary.html](https://kanlerxz87-cyber.github.io/KalshiDash3/executive-summary.html).

## Executive summary

The repository contains a static, 21-page GitHub Pages dashboard with separate
Gas Prices, Elections, Culture, Crypto and Golf pages; price charts and order-book
ladders; two scrolling swing-alert feeds; resolution tracking; and paper-strategy
and portfolio analysis. Baseline `python3 scripts/verify_release.py` passed in this
session. This confirms executable code, fixture behavior, internal links and
consistency with committed evidence, **not independently verified live prices**.

The first live collector diagnostic failed. Its official Actions check annotation
identified missing series evidence for two old gas-price alerts, not an API
outage. This session fixes that omission without weakening the validator and
publishes **F-107** on [Flagged for Review](https://kanlerxz87-cyber.github.io/KalshiDash3/flagged.html).
See the session's [coordination record](COORDINATION.md) for the actual dry-run,
merge, refresh and deployment outcomes. Historical pre-fix numbers below are
labelled and must not be read as current quotes.

**Execution is still paper only.** This session has no authenticated demo-account
connection; no account balance, actual fills, actual account P&L or successful
order execution is asserted. A public Pages deployment cannot safely store an API
private key. Real authenticated execution needs a server-side credential boundary.

## Official sources read during this session

These pages were fetched and their relevant text was read on 2026-11-27. This is a
bounded re-verification, not a re-certification of all historical ledger claims.

| Subject | What the fetched official source supports | Official source |
|---|---|---|
| Demo environment | Mock funds; credentials separate from production; demo prices/behavior may not reflect real markets; both requested REST and WebSocket hostnames documented | [Demo environment](https://docs.kalshi.com/getting_started/demo_env) |
| Streaming authentication | All WebSocket sessions require authenticated handshake, including sessions carrying public ticker/trade data | [WebSocket quick start](https://docs.kalshi.com/getting_started/quick_start_websockets) |
| Liquidity | Public orderbook returns YES and NO bids; arrays hold dollar-price/contract-count string pairs; opposite asks are complements to $1 | [Orderbook responses](https://docs.kalshi.com/getting_started/orderbook_responses) |
| Series evidence | `GET /series/{series_ticker}` returns official category/categories, tags, settlement sources and other series metadata | [Get Series](https://docs.kalshi.com/api-reference/market/get-series) |
| Specific failed series | `KXAAAGASD` returned `categories: ["Economics"]`, title `US gas price up`, settlement source AAA | [Official demo series record](https://external-api.demo.kalshi.co/trade-api/v2/series/KXAAAGASD) |
| Settlement | YES/NO winners receive $1 per contract; net positions settle; simple YES/NO settlement fees are zero | [Market settlement](https://docs.kalshi.com/getting_started/market_settlement) |
| Exchange availability | The fetched response reported `exchange_active: true` and `trading_active: true`; this is a point-in-time response, not a future uptime promise | [Demo exchange status](https://external-api.demo.kalshi.co/trade-api/v2/exchange/status) |

The platform page-fetch route reached these sources. Shell network access to
Kalshi and some GitHub log-download hosts is restricted; Actions diagnostics were
obtained through the official check-run annotations API instead of inventing log
contents. Account secrets were neither requested nor exposed.

## Citation-integrity improvement

New command:

```sh
python3 scripts/audit_sources.py
python3 scripts/audit_sources.py --json
```

It checks exact allowed demo origins, endpoint route and **ticker identity** on
market rows, both alert feeds, archived alerts, ROI rows, paper positions, catalyst
market references, series ledger entries and liquidity snapshots. The fact ledger
also requires an explicit boolean verification state, a source from an explicit
host allowlist, and blank values plus explanations for unverified facts. GitHub
citations in the fact ledger are restricted to this repository and are project
provenance, not Kalshi authority.

Unlike an `https://` prefix check or a test for the substring `demo`, it rejects
lookalike domains, production endpoints, userinfo, explicit ports, protocol-relative
URLs, backslashes, whitespace/control characters, unrelated routes and sources
pointing at another ticker. It does **not** fetch those URLs, verify their current
availability or certify the values stored beside them. A correct citation can still
accompany an incorrect claim; that remains a separate verification task.

`test_source_audit.py` is discovered automatically by the existing release gate.
It tests both rejection fixtures and the actual committed public records, and
fails closed for missing required documents or row groups. No snapshot is changed
by either the audit or its tests.

### Pre-fix snapshot audit (as of `2026-11-27T18:00:57Z`)

All counts in this section are **counts of stored links/rows**, not independently
re-fetched market observations. The same row can occur in multiple feeds; these
are not counts of unique events or unique markets. Empty ROI pick lists are not
evidence that no profitable opportunities exist.

| Stored evidence checked | Rows | Source/provenance for manual review |
|---|---:|---|
| Published open markets | 514 | [Committed official-API snapshot](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/markets.json) |
| Published settled markets | 200 | [Committed official-API snapshot](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/markets.json) |
| Official series citation ledger | 442 | [Committed series ledger](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/markets.json) |
| Liquidity/orderbook citations | 20 | [Committed orderbook records](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/markets.json) |
| All-event alert feed | 154 | [Alert feed](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/alerts.json) |
| Experimental filtered alert feed | 123 | [Alert feed and rule disclosure](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/alerts.json) |
| Archived alerts, including withheld rows | 174 | [Alert archive](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/alerts_archive.json) |
| Fee-aware ROI unscoreable rows | 8 | [ROI output](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/roi.json) |
| Paper positions, open / settled | 54 / 7 | [Paper simulation output](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/simulation.json) |
| Catalyst rows, each with market and settlement-reference citation | 154 | [Catalyst output](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/live/catalysts.json) |
| Fact-ledger citations / explicitly unverified blank facts | 72 / 1 | [Fact ledger](https://github.com/kanlerxz87-cyber/KalshiDash3/blob/main/data/verified_facts.json) |

## Collector defect and regression

[Diagnostic run 46058016625](https://github.com/kanlerxz87-cyber/KalshiDash3/actions/runs/46058016625)
collected successfully but failed `validate_alerts`. Its
[official check annotation](https://api.github.com/repos/kanlerxz87-cyber/KalshiDash3/check-runs/140705144837/annotations)
named two `KXAAAGASD-26NOV21-3.6600` archive entries: the alerts retained a topic
assignment from official series categories, while the next snapshot lost the
series entirely when its markets left the scan window.

The fix extends `collect.py`'s existing archive watch block: every distinct archived
series is recorded using the same official lookup as scanned series. Existing
ledger entries deduplicate requests. A failed API answer remains null; no stored
historical category is copied forward as if newly verified.

The new end-to-end fixture runs the **real collector build → alert builder →
strict alert validator**, with no currently scanned gas market and no bulk series
answer. It confirms that the official per-series fixture is requested once and the
validator passes. Separate cases cover an unavailable API answer, a changed
current category, and an official bulk answer avoiding an extra request. No
validator code or threshold is changed.

## Standing limitations and priorities

- **Polling is not a continuous tick stream.** Snapshot deployment and data
  collection are separate health states. Browser REST polling is subject to CORS,
  caching and rate limits; authenticated streaming needs a server-side service.
- **“Highest dollar amount” is an estimate:** existing ranking uses cumulative
  contract volume × last price, not actual dollar turnover or available liquidity.
- **Two filters, not two proven models:** the historical alert screen and the
  fee-aware ROI screen are distinct experimental definitions. Neither establishes
  future returns; do not confuse a screen flag with investment advice.
- **Attribution is unverified:** a source relevant to settlement or a news search
  lead does not prove why a particular price jump occurred. Missing causes stay
  blank rather than being invented.
- **Resolution/sample coverage is bounded.** Published rows are a selected window,
  not a proof of exhaustive exchange history; seven historical simulated
  settlements are not enough to establish a profitable strategy.
- **Pages configuration remains a review item.** The repository API reported
  `build_type: legacy`, with `main /` as its source. The verified Actions pipeline
  is additional protection, not proof that legacy publication cannot bypass it.

The existing [review ledger](https://kanlerxz87-cyber.github.io/KalshiDash3/flagged.html)
and [suggestions](https://kanlerxz87-cyber.github.io/KalshiDash3/suggestions.html)
retain these disclosures. Recommended next work: a private authenticated streaming
backend with reconnect/gap recovery; account/order reconciliation and risk limits;
walk-forward model validation; and timestamped official catalyst evidence clearly
separated from causal hypotheses. Those are recommendations, not claims of work
completed in this session.

## Publication and live-recovery outcome

- [PR #151](https://github.com/kanlerxz87-cyber/KalshiDash3/pull/151) merged at
  **2026-11-27T19:45:39Z**, commit `9a57035`, after its release check passed.
- [Main collector recovery](https://github.com/kanlerxz87-cyber/KalshiDash3/actions/runs/46058978690)
  succeeded and committed snapshot **2026-11-27T19:47:49Z** (`3cb118b`):
  **614 open / 200 settled published rows**. The official archived gas-series
  citation is present; the strict validator passed.
- [Fresh-data Pages release](https://github.com/kanlerxz87-cyber/KalshiDash3/actions/runs/46059212091)
  built and deployed successfully, completed **19:50:54Z**. A subsequent live
  fetch of `index.html` displayed that snapshot and those row counts; the public
  health JSON reported `outcome: ok`, not the earlier failed state.
- The full offline release gate passed again against that refreshed main tree.
  The source audit passed against its 614 open, 200 settled and 514 series records
  plus the covered alert, ROI, simulation and catalyst rows. The earlier table
  deliberately remains a labelled **pre-fix** audit, not a current-price table.
- The [default collector relay](https://github.com/kanlerxz87-cyber/KalshiDash3/actions/runs/46059242833)
  was restarted and recorded another successful snapshot at **19:50:00Z**.
  This verifies recovery, not an indefinite uptime or future-cadence guarantee.

A concurrent independent repair appeared as PR #152 after #151 was merged; the
[coordination comment](https://github.com/kanlerxz87-cyber/KalshiDash3/pull/152#issuecomment-7226869681)
prevents silent duplicate integration and duplicate finding IDs. That PR and the
other sessions' work were not merged, closed or overwritten by this session.

### Concurrent integration update

PR #152 subsequently merged to main as `8f4aae7` while this close-out was being
prepared. Its separately verified changes are preserved: a historical official
series-record fallback when a fresh answer is unavailable, explicit handling of
unknown categories, and richer validator failure diagnostics (F-108/F-109). The
PR #151 runtime re-fetch remains the primary mechanism. The regression's negative
control now tests an explicit contradictory official category rather than treating
an unknown category as a contradiction. The newer collector snapshot is retained
verbatim from main. This audit does not relabel the fallback as a fresh API answer.
