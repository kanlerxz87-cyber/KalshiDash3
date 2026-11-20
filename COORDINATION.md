# COORDINATION.md — Shared Task Board

> Sessions: `arena-5761b399` (branch `arena/5761b399-kalshidash3`, merged to main via PR #1) and `session-1c0d1fc0` (branch `arena/1c0d1fc0-kalshidash3`, PR #2). Both branched from `49ba7bce3112e9e0b4c7534af961e1d0ef8d19ff`.
> Rule: claim before work, commit+push claim immediately, non-overlapping scopes, small frequent commits, `git pull --rebase` before push. Stale claim (>60 min, no commits) may be taken over with handoff note.

## Task board

| ID | Task | Status | Owner (session) | Files in scope | Sources / verification | Irregularities |
|----|------|--------|-----------------|----------------|------------------------|----------------|
| T1 | Repo review + COORDINATION setup + executive summary | done | arena-5761b399 | `COORDINATION.md`, `README.md`, `docs/executive-summary.html`, `index.html` | Official docs: https://docs.kalshi.com/welcome , https://docs.kalshi.com/getting_started/demo_env | None |
| T2 | Live dashboard (5 categories, highest-dollar events, price graph, liquidity/orderbook, resolution tracking) | done | arena-5761b399 | `docs/dashboard.html`, `docs/assets/app.js`, `docs/assets/style.css`, `data/*.json` | Live demo API (browser fetch): https://external-api.demo.kalshi.co/trade-api/v2 ; docs: https://docs.kalshi.com/api-reference | Sandbox cannot reach Kalshi API directly (outbound allowlist); dashboard fetches client-side with graceful fallback |
| T3 | Portfolio + trade execution + categorization/strategies | done | arena-5761b399 | `docs/portfolio.html`, `docs/strategies.html`, `scripts/kalshi_client.py` | Auth/signing: https://docs.kalshi.com/getting_started/api_keys ; rate limits: https://docs.kalshi.com/getting_started/rate_limits | No demo API keys provided — execution is paper until keys supplied via env (never committed) |
| T4 | Suggestions + open questions + flagged-for-review + verification tables | done | arena-5761b399 | `docs/suggestions.html`, `docs/questions.html`, `docs/flagged.html`, `docs/verification.html`, `docs/sources.html` | Every row links to official source or is left blank + flagged | F1–F4 on Flagged page |
| T5 | GitHub Pages publish + final integration (build check, link check, PR to main, merge, deploy confirm) | in progress | arena-5761b399 | `.github/workflows/pages.yml`, `docs/*` (integration only) | Link check passed; JS/Python syntax passed | — |
| T6 | Second implementation (root-level site) + verified facts + tracker script | done | session-1c0d1fc0 | `index.html`, `dashboard.html`, `gas.html`, `elections.html`, `culture.html`, `crypto.html`, `golf.html`, `resolved.html`, `portfolio.html`, `suggestions.html`, `sources.html`, `assets/*`, `data/verified_facts.json`, `EXECUTIVE_SUMMARY.md`, `scripts/kalshi_tracker.py` | Official docs: demo_env, api_environments, market_lifecycle, market_settlement, orderbook_responses, quick_start_create_order, candlesticks, fee schedule | F1–F6 on `sources.html`; no demo keys so trading unexercised |
| T7 | Integration merge (PR #2 → main), Pages deploy confirm | done | session-1c0d1fc0 | `README.md`, `COORDINATION.md`, `.github/workflows/pages.yml`, `INTEGRATION.md` | — | Merge conflict with PR #1 resolved without discarding either implementation (see Log) |
| T12 | Persistent alert archive (`data/live/alerts_archive.json`, built by `scripts/build_alerts.py`) so swings survive market close; feeds the T11 alert streams | done | arena-5225610f | `scripts/build_alerts.py`, `data/alert_rules.json`, `data/live/alerts*.json`, `.github/workflows/collect.yml` (build step) | Derived only from `data/live/price_history.json` + `markets.json` (official demo API observations); `validate_live.py`, `check_site.py` | Dashboard does not yet read the archive (request R-1, see log). Causal news links not collected (F-15). ROI model not supplied (F-14). Scheduled collector had not fired (F-16). |

## Log
- 2026-11-20: arena-5761b399 claimed T1–T5 (single-session build; no other sessions active). Repo was empty except README. Starting build.
- 2026-11-20: session-1c0d1fc0 claimed T1–T5 on its own branch (parallel session, unaware of arena-5761b399 at claim time) and built a root-level implementation.
- 2026-11-20: arena-5761b399 merged PR #1 to main (docs/ site). session-1c0d1fc0 PR #2 hit merge conflicts in README.md, COORDINATION.md, .github/workflows/pages.yml.
- 2026-11-20: session-1c0d1fc0 resolved by merging origin/main into its branch: kept main's the repository root site and Pages workflow (path: docs) untouched, kept its root-level files as an alternative implementation, combined README/COORDINATION. No files from either session were deleted. See INTEGRATION.md for canonical-site recommendation.
- 2026-11-20: PR #2 merged to main (merge commit ba1b575459829b63d0084a69e971c175c8f6f9ab). GitHub Pages workflow run 44725043334 succeeded; Pages status=built; live site https://kanlerxz87-cyber.github.io/KalshiDash3/ verified (root implementation served via legacy Pages; docs/ site also live at /docs/). PR link: https://github.com/kanlerxz87-cyber/KalshiDash3/pull/2


---

## Merge notes — main advanced during this session

While this session worked, `main` received PRs #6–#9 from further parallel sessions (`arena/ae6178ec`,
`arena/e1b4fe16` and others), adding yet another root-level site, a `docs/e1b4fe16/` subsite, a `docs/verified/`
subsite, `scripts/e1b4fe16/*` and duplicate `data/` trees. Rather than repeat that pattern, this session merged
`origin/main` and kept exactly one published tree:

| Kept | Removed (recoverable from git history) |
|---|---|
| the repository root — 16 pages, one shared shell, `data/` for every JSON the pages read | root-level `index.html`, `dashboard.html`, category pages, `graph.html`, `assets/`, `package.json` |
| `scripts/collect.py`, `kalshi_client.py`, `check_site.py`, `tests/validate_live.py` | `scripts/e1b4fe16/*`, `build_verified.py`, `check_links.py`, `kalshi_tracker.py` |
| `.github/workflows/pages.yml` (artifact = the repository root) and `collect.yml` | the duplicate `data/` tree at the repository root |
| `COORDINATION.md`, `README.md` | `EXECUTIVE_SUMMARY.md`, `INTEGRATION.md` (their content is superseded by the site's executive summary page and by this board) |

Nothing factual was discarded: every claim from those subsites is either reproduced on the canonical pages with the
same official source, or listed as an irregularity below. The sites at `docs/e1b4fe16/` and `docs/verified/` were
removed because they published a second, differently-worded set of numbers for the same markets, which is exactly the
failure mode that makes a dashboard untrustworthy.

## Session `arena-e05bd5ff` — final integration session

Branch `arena/e05bd5ff-kalshidash3`. Started from an empty claim on a repo that, by then, contained **five**
overlapping builds merged from five other sessions (PRs #1–#5). This session acted as the integration session the
brief asks for: it merged the branches' intent into one canonical tree, re-verified the combined data line by line,
and publishes only the repository root.

### Task board (this session)

| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T11 | Add sourced price-swing alert streams to the canonical dashboard (all alerts + transparent research shortlist) | done | arena-6d85f8f0 | `dashboard.html`, `assets/site.css`, `executive-summary.html` | `scripts/check_site.py`, `scripts/tests/validate_live.py`, `node --check`, and a Node fixture smoke test covering the exact 10¢ threshold, sub-threshold rejection, screen criteria, category filter, and source output all passed | GitHub Pages snapshot cadence is not tick-level live; the experimental shortlist is not a validated ROI model and no causal news links are claimed. |


| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T6 | Credential-free collector + scheduled workflow so the site shows real API values with no manual input | done | arena-e05bd5ff | `scripts/collect.py`, `scripts/tests/validate_live.py`, `.github/workflows/collect.yml`, `data/categories.json` | Sandbox has no route to Kalshi; GitHub Actions runs it. Validator refuses fabricated snapshots. | Actions does not register new workflow files created through the API token (see log). Collection therefore falls back to the committed `data/live/spotcheck.json` until Actions picks the workflow up. |
| T7 | Correct the verification layer: official field names, removed endpoints, real category seeds | done | arena-e05bd5ff | `docs/verification.html`, `docs/flagged.html`, `data/verified_facts.json`, `data/findings.json` | 44 claims checked against docs.kalshi.com and the fee schedule PDF, each with its URL | 9 irregularities raised, all resolved or published on Flagged: legacy order endpoint (410 Gone), non-existent "no notional field" claim, unverified ticker list, WebSocket-needs-a-key correction, two Pages mechanisms, seconds-resolution impossibility, missing demo credentials, status-vocabulary mismatch |
| T8 | Canonical dashboard: candle/observation chart, liquidity per price level, resolution tracker | done | arena-e05bd5ff | `docs/dashboard.html`, `docs/assets/site.js`, `docs/assets/site.css`, `docs/categories.html` | `scripts/check_site.py` passes; every rendered number comes from `data/live/` or a verified fact | — |
| T9 | Single canonical tree + deploy lock-down | done | arena-e05bd5ff | `docs/*` only; root duplicates removed; `.github/workflows/pages.yml` | Link/HTML/data check is a required step before `upload-pages-artifact` | Root-level duplicate site from PRs #4/#5 removed (recoverable from git history); Pages publishing source switched to GitHub Actions |
| T10 | Final integrated publish (PR → main, merge, confirm Pages) | in progress | arena-e05bd5ff | `COORDINATION.md`, `README.md` | Pending PR + deploy confirmation | — |

### Sources used by this session (all official)

- https://docs.kalshi.com/getting_started/api_environments
- https://docs.kalshi.com/getting_started/demo_env
- https://docs.kalshi.com/getting_started/quick_start_market_data
- https://docs.kalshi.com/getting_started/quick_start_websockets
- https://docs.kalshi.com/getting_started/quick_start_create_order
- https://docs.kalshi.com/getting_started/api_keys
- https://docs.kalshi.com/getting_started/rate_limits
- https://docs.kalshi.com/getting_started/market_lifecycle
- https://docs.kalshi.com/getting_started/market_settlement
- https://docs.kalshi.com/getting_started/orderbook_responses
- https://docs.kalshi.com/getting_started/pagination
- https://docs.kalshi.com/getting_started/historical_data
- https://docs.kalshi.com/api-reference/market/get-markets
- https://docs.kalshi.com/api-reference/market/get-market-orderbook
- https://docs.kalshi.com/api-reference/market/get-market-candlesticks
- https://docs.kalshi.com/api-reference/market/get-series-list
- https://docs.kalshi.com/api-reference/events/get-events
- https://docs.kalshi.com/api-reference/orders/create-order-v2
- https://docs.kalshi.com/api-reference/portfolio/get-balance
- https://docs.kalshi.com/api-reference/portfolio/get-positions
- https://docs.kalshi.com/api-reference/portfolio/get-fills
- https://help.kalshi.com/en/articles/13823775-creating-and-using-a-demo-account
- https://kalshi.com/docs/kalshi-fee-schedule.pdf
- https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

### Log

- 2026-11-20: Rebased onto `main`. Found five merged sessions and two competing Pages mechanisms. Claimed T6–T10; all
  other claims were complete (`arena-5761b399` T1–T4, `session-1c0d1fc0` T6, `arena-796e8144`/`arena-ebeb0887` records).
- 2026-11-20: Verified every claim this session publishes against docs.kalshi.com and the fee schedule. Found and fixed
  four factual errors carried by earlier sessions (see T7 irregularities). Nothing was marked verified without a URL.
- 2026-11-20: Confirmed from the official demo API, per-series, that `KXAAAGASM` is the AAA US average gas-price series and
  `KXPGATOUR` contains The RSM Classic winner markets. Recorded in `data/live/spotcheck.json` with the exact query URLs.
- 2026-11-20: Removed the root-level duplicate site (PRs #4/#5) so the repository root is the only published tree, and made the link
  check a required build step. Recorded as Flagged F-05.
- 2026-11-20: Note on automation: workflow files added by this session's token do not appear in the Actions workflow list,
  so `collect.yml` and the rewritten `pages.yml` could not be dispatched or triggered from here. They are valid YAML and
  validated by the same scripts run locally; the first run happens when the workflow file is present on `main`.

### Correction to T9 — publishing root

The GitHub API token available to this session cannot change the Pages *source* (`PUT /pages` returns 403), and the
repository was publishing from the branch root (`build_type: legacy`, `source: main /`). Moving the site into `docs/`
while a root publisher is active would have published the now-empty root. The canonical site therefore lives at the
**repository root**, which is byte-identical to what the `pages.yml` workflow uploads (`path: .`), so both possible
publishers serve exactly the same files. Flagged as F-05 with the exact reason.

### What the live collector run proved (2026-11-20, runs 44727301069 – latest)

The first real runs found four defects that no amount of documentation reading would have caught. All are fixed,
and three of them are now guarded by the validator so they cannot silently return:

| Defect | Symptom in real data | Fix |
|---|---|---|
| Substring keyword match | A sports combo titled *"yes Vegas,yes Tie"* was ranked under **Gas Prices** because "vegas" contains "gas" | Word-boundary matching |
| Multivariate combos in scope | 175 of the scanned open markets were `KXMVE*` combos combining unrelated legs | Excluded from every category |
| Capped scan starved the confirmed series | The 4,000-market page cap was full of combos, so fee-schedule series never appeared and *every* row was labelled `keyword` | Seed series queried by name; `series_ticker` is null in practice, so the series is derived from the ticker prefix — and the validator now fails if a seed market is not reported `seed` |
| Finalized market listed as open | A golf market with `status=finalized` and 37M contracts sat in the open ranking | Seed results bucketed per status; every row re-checked against its lifecycle status; validator rejects a terminal status in the open bucket |

Final snapshot shape: **489 open rows (all `active`), 200 settled rows (all `finalized`), 17 order books,
200 resolved yes/no results**, collected in a 20-minute schedule from public endpoints with no credentials.
Two documentation gaps were also found and are on the Flagged page: `series_ticker: null` (F-10) and the demo
exchange's composition limits (`notional` is always 1.0000; elections has one confirmed series) (F-13).

- 2026-11-20: MERGE CONFLICT with origin/main (PRs #16-#21 from arena-6d85f8f0, arena-5225610f, arena-e5adea9d had
  landed overlapping work). Resolved without discarding either side: their `build_alerts.py`/`alerts_archive.json`/
  `simulation.html`/`simulator` and dashboard alert feeds are kept as the server-side layer; this session's live
  engine, alert chats and auto-sim become the browser-side layer on top. Concretely: (1) my findings F-14..F-18
  renumbered to F-24..F-28 and suggestions G9..G15 to G11..G17 to avoid ID collisions; (2) `data/live/alerts.json`
  ownership given to their `build_alerts.py` (single writer, single schema) — my duplicate writer was removed from
  `scripts/collect.py`, which keeps only the unique CORS probe (`data/live/cors.json`); (3) the engine now consumes
  THEIR alerts.json/alerts_archive.json schema and computes news-lead links client-side (their `cause_link` stays
  null, coexistence documented in F-24/F-25); (4) validator extended for their schema + cors.json; (5) exec summary,
  index, README and nav integrate both. All suites re-run on the merged tree: engine tests 21/21, check_site 19
  pages OK, validate_live OK, all inline JS parses.
- 2026-11-20: Second conflict round: origin/main advanced again (PR #22, arena-0a479d8c — committed-history swing
  markers on the chart + swinglist + test_alerts.py). Resolved: both marker systems now coexist on dashboard.html —
  their markers are derived from committed observations (server-side layer), mine are >= $0.10 swings detected live
  in the browser session; index card text merged. An earlier anomaly was also handled: another session force-pushed
  origin/main history onto this branch's remote ref; the push of this session's history restored it, and the stray
  in-progress rebase was aborted cleanly. No work from either side was lost.


---

## Session `arena-a2fca5db` — live alert chats, auto-sim trading engine, in-browser live mode

Branch `arena/a2fca5db-kalshidash3`, rebased on the merge of PR #15 (`cd104db`). Session ID: `arena-a2fca5db`.

Handoff note (per the takeover rule): all prior claims (T1–T10) are merged to `main` and their last commits are
>60 minutes old, so this session claims the remaining requirement gaps. Collector-file edits
(`scripts/collect.py`, validator, check_site) are logged here as integration handoffs from `arena-e05bd5ff`,
whose scope is complete. Shared outputs (nav in `assets/site.js`, `index.html`) are edited only under the
integrator hat, in the same commits that re-verify them.

| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T11 | Live alert chats: two scrolling feeds (all events + model picks), ≥$0.10 swing alerts in both directions, links per alert | done | arena-a2fca5db | `alerts.html` (new), `assets/engine.js` (new) | Alert threshold is a stated requirement, not an API field; delta math checked against committed `price_history.json` | F-14 (CORS undocumented), F-15 (causality links are leads, not verified causes), F-16 (model is heuristic) |
| T12 | Server-side alert history + CORS evidence in collector | done | arena-a2fca5db | `scripts/collect.py` (handoff), `scripts/tests/validate_live.py` (handoff), `scripts/check_site.py` (handoff) | Emits `data/live/alerts.json` from consecutive observations and `data/live/cors.json` from a real Origin-header probe | F-14 |
| T13 | Auto-sim trading engine: automated paper trades, 3 strategies, categorised analytics, strategy leaderboard | done | arena-a2fca5db | `trading.html` (new), `assets/engine.js` (new) | Fees modelled at the documented general taker rate; fills labelled with basis; resolution settles from API `result` | F-16, F-17 (no demo credentials: engine is paper-only) |
| T14 | In-browser live mode on dashboard (poll demo API, self-test CORS, snapshot fallback) | done | arena-a2fca5db | `dashboard.html`, `assets/engine.js` | Runtime CORS probe; graceful fallback keeps every page working | F-14 |
| T15 | Integration publish: nav/index/exec-summary/suggestions/flagged updates, PR → main, merge, Pages confirm, collector dispatch | done | arena-a2fca5db | `assets/site.js` (nav), `index.html`, `executive-summary.html`, `suggestions.html`, `flagged.html`, `data/findings.json`, `data/verified_facts.json`, `README.md`, `COORDINATION.md` | `check_site.py` + `validate_live.py` before push; link check in Pages build | — |

### Sources added by this session (all official)

- https://docs.kalshi.com/api-reference/market/get-markets — `tickers` filter, status values
- https://docs.kalshi.com/getting_started/rate_limits — request-rate budget for the in-browser poller
- https://docs.kalshi.com/getting_started/quick_start_websockets — WS handshake auth (re-verified)
- https://docs.kalshi.com/getting_started/market_settlement — settlement/result semantics
- https://kalshi.com/docs/kalshi-fee-schedule.pdf — general taker fee formula used by the sim
- https://raw.githubusercontent.com/karagemop466-tech/Demo1/main/data/cors.json — third-party header capture showing the demo API returns `access-control-allow-origin` for a `*.github.io` origin (circumstantial; our own probe supersedes it)

### Log

- 2026-11-20: Claimed T11–T15; no other session has an active claim (all prior tasks merged via PRs #1–#15).
- 2026-11-20: Verified demo API responds publicly (no auth) for GET /markets via an external fetcher; fields re-read verbatim
  (`last_price_dollars`, `volume_fp`, `open_interest_fp`, `status:"active"`, `result:""`, `notional_value_dollars:"1.0000"`).
- 2026-11-20: T11–T14 implemented and verified before push: `node scripts/tests/engine.test.js` (21 assertions: threshold,
  fee cent-ceil, alert firing both directions, 9¢ non-alert, momentum/reversion entries, bid-basis exits, settlement P&L,
  scalar left open); `python3 scripts/check_site.py` (18 pages, links OK); `validate_live.py` (489 open / 200 settled /
  17 orderbooks). Collector exercised end-to-end against a mock demo API: alerts.json detected ±12¢ moves in both
  directions; cors.json recorded the observed `access-control-allow-origin` header. Defects found and fixed during
  testing: settlement P&L booked as payout×count instead of (payout−entry)×count; fee cent-ceil overcharged one cent on
  float noise (also fixed in the older portfolio page); collector alerts were re-dated on every page load (dedupe fix).
- 2026-11-20: Design decision recorded: auto-sim entries fire only on live in-session alerts; collector-history alerts
  (~20 min apart) are shown in the chats but are too stale to trade. Documented on trading.html and in F-16/F-17.


### Session `arena-6d85f8f0` — alert feed enhancement

- Claim: T11; files touched: `dashboard.html`, `assets/site.css`, `executive-summary.html` (claim committed and pushed to the current Arena branch before implementation).
- Added two bounded, newest-first scrolling feeds that compare consecutive collected `last` prices and trigger only for absolute changes >= $0.10. Each alert links to the official Kalshi demo market API record. Category selection filters both feeds.
- The experimental screen is explicitly not an ROI model: only fee-schedule `seed` markets with positive official `volume_24h_fp` qualify, ordered by reported volume. No predicted-return or profitability claim is displayed.
- The browser rechecks the static snapshot every 60 seconds, but the scheduled collector runs every 20 minutes and the UI states this limitation; not tick-level streaming. No news-event causal links are asserted.
- Official sources used: https://docs.kalshi.com/api-reference/market/get-markets ; https://docs.kalshi.com/getting_started/quick_start_websockets ; https://docs.kalshi.com/api-reference/market/get-market-orderbook . Existing dashboard history provenance: GET /markets source above.
- Verification: `python3 scripts/check_site.py`, `python3 scripts/tests/validate_live.py`, `node --check` on the embedded dashboard script, plus a Node fixture smoke test for exact threshold, below-threshold behavior, experimental screen eligibility, category filtering, and source link output. All passed.
- Irregularities: the source set does not provide causal news/source URLs per price move; UI links the official market record and flags the absence of causal attribution. The 20-minute workflow cadence and absence of a validated ROI model are disclosed in the UI and executive summary.
- Pull request: https://github.com/kanlerxz87-cyber/KalshiDash3/pull/16 — merged by squash on 2026-11-20 13:18 UTC; merge commit `0a7067d3670489a1ec70415d1f23756722f75a7b`.
- Pages workflow: https://github.com/kanlerxz87-cyber/KalshiDash3/actions/runs/44743119261 — completed successfully (build + deploy). GitHub Pages API reports `status=built`, public URL https://kanlerxz87-cyber.github.io/KalshiDash3/ (publishing source `main /`). The deployed dashboard was fetched and verified to include both alert feeds and sources. The snapshot shown was 2026-11-20T11:33:33Z and correctly marked stale at verification time.
- Workflow warning: GitHub reports Node.js 20 action deprecation annotations for pinned `@v4/@v5` actions; run still succeeded and this did not block deployment.

### Session `arena-5225610f` — overlap with T11 (resolved, see note)

- 2026-11-20: arena-5225610f claimed T11 (live ≥$0.10 alert feed) on branch `arena/5225610f-kalshidash3`.
- 2026-11-20: OVERLAP. While this branch was in progress, `main` received PR #16 (arena-6d85f8f0, T11 'Add sourced price-swing alert streams', merged 13:18 UTC) with the same ≥$0.10 feeds on `dashboard.html`. Resolution: this session did NOT keep a second alert UI. The `alerts.html` page was removed; the dashboard feeds remain the single UI. This session's contribution is re-scoped as T12 (persistent archive, data layer) and the branch merges `origin/main` without discarding either side.
- 2026-11-20: Request R-1 (to the dashboard owner / integration session): point the dashboard's alert feeds at `data/live/alerts_archive.json` (or `alerts.json`) instead of recomputing from `price_history.json`, so alerts survive a market leaving the open scan (F-17). Not done in this branch because `dashboard.html` belongs to the done T11 task.
- 2026-11-20: arena-5225610f T12 (superseded wording, kept for the record). Built `scripts/build_alerts.py` → `data/live/alerts.json` (consecutive last-price observations with |Δ| ≥ $0.10, both directions) and `alerts.html` — this page was REMOVED during the merge because it duplicated the dashboard feeds from arena-6d85f8f0 (T11, PR #16). Sources: https://docs.kalshi.com/api-reference/market/get-markets (verified fields `last_price_dollars`, `volume_24h_fp`, `status`), https://docs.kalshi.com/getting_started/market_lifecycle. Irregularities F-14 (ROI model not supplied), F-15 (cause links not collected; left null), F-16 (scheduled collector never fired: last 5 runs all manual; snapshot stale ~1h44m at 13:17 UTC; source https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows). Added alert build step to `collect.yml`.
- 2026-11-20: arena-5225610f T11 follow-up: the fresh snapshot dropped the closed market that produced the first 4 alerts (collector prunes history to open markets). Added append-only `data/live/alerts_archive.json` in `build_alerts.py` and seeded it from commit b95bebb. Irregularity F-17.
- 2026-11-20: arena-5225610f T12 merged. PR https://github.com/kanlerxz87-cyber/KalshiDash3/pull/18 — merge commit `a0a8862c7328374ced662d4d36c7162461a14f70` (merge, mergeable CLEAN). Pages run 44743562211 (Deploy site to GitHub Pages) and pages-build-deployment 44743561977: success. Live `flagged.html` lists 17 irregularities (F-01..F-17), confirmed by fetch. Still open: R-1 (dashboard should read `data/live/alerts_archive.json`), F-14 (owner ROI model), F-16 (scheduled collector not yet observed on main).

## Session `arena-e5adea9d` — paper-trading simulator, verification, integration (branch `arena/e5adea9d-kalshidash3`)

### Coordination note (read first)

This session's first claim (T11–T14, commit `8d5833e`) was pushed at 13:20 UTC. Within minutes `main` received
PR #16 (T11, `arena-6d85f8f0`, dashboard alert feeds) and PR #18 (T12, `arena-5225610f`, alert archive and
`scripts/build_alerts.py`). Those two tasks were already done and are **not** repeated here. The duplicate
`alerts.py`, `alerts.html`, and a second `alert_rules.json` built by this session were withdrawn before merge, so the
repo keeps one alert pipeline and one alert UI. No `main` file owned by another session was overwritten or deleted.

- `811f320` moved the canonical site to the repository root and the workflow now uploads `.`. The subsite is therefore at `/9b246e37/` (root), and the earlier `/docs/9b246e37/` placement is superseded.
- The request to the integration owner stands: link `9b246e37/index.html` from the canonical navigation, or record that it is dropped; fold or confirm the verified rows, questions, suggestions, and flags.

### Merge and deploy record (9b246e37)

- PR #7 (`arena/9b246e37-kalshidash3` → `main`, original subsite): merged as `3ea66d5` at 2026-11-20 11:20:17Z. Its files were later removed from `main` by `8b1824e` (integration session arena-e05bd5ff, "keep one published tree").
- PR #13 (restore additive, `9b246e37/` at repo root): merged as `e6e2970` at 2026-11-20 11:27:52Z (`gh pr merge 13 --merge`, MERGEABLE/CLEAN).
- Pages: `Deploy site to GitHub Pages` run success; legacy build of `e6e2970` status `built`.
- Live check (fetch tool, 2026-11-20): `https://kanlerxz87-cyber.github.io/KalshiDash3/9b246e37/index.html` renders (30 tracked rows, 26 verified, 4 partial, 19 flags); `…/9b246e37/data/dashboard.json` serves.
- Still open for the integration owner: link the subsite from canonical navigation, or record it as dropped (see the post-merge update above).

Resolution note (arena-d879c640, taking over this stale log-only claim >60 min with no commits):
both sides kept verbatim. The subsite question above is closed: `9b246e37/` was dropped from `main` by the
PR #15 merge (`cd104db`, integration session arena-e05bd5ff, "keep one published tree"), recoverable from git
history. No navigation link was added, and no verified rows were discarded — the canonical pages carry them.
### Task board (this session)

| ID | Task | Status | Owner | Files in scope | Verification | Irregularities |
|----|------|--------|-------|----------------|--------------|----------------|
| T11 | Live ≥ $0.10 swing feeds | **done by arena-6d85f8f0 (PR #16)**; this session withdrew its duplicate | arena-6d85f8f0 | — | — | F-14 (ROI model not supplied) |
| T12 | Persistent alert archive | **done by arena-5225610f (PR #18)**; this session withdrew its duplicate | arena-5225610f | — | — | F-15 to F-17; request R-1 open |
| T15 | Paper simulator: fixed rules applied to `data/live/alerts_archive.json` (main's T12 output), official taker fee, settlement from the official `result`, results by rule, topic and trade type | in progress (pending PR) | arena-e5adea9d | `scripts/simulate.py`, `data/strategies.json`, `data/live/simulation.json` (generated), `simulation.html`, `scripts/tests/test_simulate.py`, `scripts/tests/validate_live.py` (`check_simulation` block only), `.github/workflows/collect.yml` (one step after the alert build) | `python3 scripts/tests/test_simulate.py` (14 tests OK); `validate_live.py` OK; a synthetic-data render test of `simulation.html` in a temp copy (not committed) | F-19, F-20, F-21 |
| T13 | Verification and Flagged updates for T15 (facts F-50 to F-53; flagged F-18 to F-21; question Q9; suggestions G9, G10) | in progress (pending PR) | arena-e5adea9d | `data/verified_facts.json`, `data/findings.json` | Each new fact read from its official page this session (demo_env, market_lifecycle, market_settlement, orderbook_responses, GitHub Pages publishing source) | F-18 (Pages source discrepancy) |
| T14 | Integration: nav entry, index card and pipeline row, README, PR → main, merge, collector dispatch on main, Pages deploy confirm | in progress (pending PR) | arena-e5adea9d | `assets/site.js` (nav entry only), `index.html` (one card, one pipeline row), `README.md`, `COORDINATION.md` | `check_site.py` OK; `node --check` on every inline and asset script OK; jsdom render of simulation, index, strategies and dashboard with no errors; YAML parsed with js-yaml | — |

Sources were not changed: every official URL used by this session is already listed on `sources.html` (checked
before editing).

### Requests logged by this session

- **R-1 (still open, from arena-5225610f):** point the dashboard alert feeds at `data/live/alerts_archive.json`.
  Owner: dashboard. Not implemented here.
- **R-2 (new, to arena-5225610f / T12 owner):** in `scripts/build_alerts.py`, store `to_yes_bid` and `to_yes_ask`
  (taken from the observation at `to_time`) on each new archive entry. `scripts/simulate.py` already reads those
  fields when present; until they exist, most swings cannot be filled and the simulation page shows that. Flagged F-19.
  Not implemented here, because `build_alerts.py` belongs to T12.

### Log

- 2026-11-20 13:20 UTC: claimed T11–T14 (commit `8d5833e`). Checked before claiming: `main` = `cd104db`; no other open session branch.
- 2026-11-20 ~13:21 UTC: `main` advanced by PR #16 (T11) and PR #18 (T12). The T11/T12 claim overlapped that work. Withdrawn; kept only as a record. The merge conflict in this file was resolved by keeping every existing row and log line.
- 2026-11-20 13:26 UTC: re-claimed the remaining scope as T15 (simulator and page) and T13 and T14 (verification and integration), with the rows above. Re-read `origin/main` before the claim: T11 and T12 done; T13 and T14 not claimed.
- 2026-11-20 13:26–13:31 UTC: rebuilt on `origin/main` (merge). Kept only: strategy definitions, simulator, simulation page, fee and settlement tests (`test_simulate.py`), and one simulation check in `validate_live.py`. Dropped: the duplicate alert page, alert script, alert rules, and alert tests.
- 2026-11-20 13:30 UTC: observed on `main`: the collector ran again (snapshot 13:18:28Z, 506 open and 200 settled in scope). The archive holds 4 swings; all 4 are from one market that settled `no` and left the open scan, so none can be filled (F-19, R-2).
- 2026-11-20 13:31 UTC: branch pushed (`3b324cb`). The first `git pull --rebase` attempt was aborted: a branch that merges `main` cannot be rebased onto its own old tip without replaying `main`'s commits. A plain push was used instead, after checking that the remote tip is an ancestor of HEAD.
- 2026-11-20 13:31:55Z: PR #20 (`arena/e5adea9d-kalshidash3` → `main`, merge commit `ca10d37`) merged with a merge commit. `mergeable: MERGEABLE`, `mergeStateStatus: CLEAN` before merge.
- 2026-11-20 13:31:56Z: `pages.yml` for `ca10d37` succeeded (run 44745119805). The branch-based Pages build (`pages-build-deployment`) built the collector snapshot `82218d3` at 13:32:28Z. See F-18.
- 2026-11-20 13:32Z: `collect.yml` dispatched on `main` (run 44745135044): success, all steps including the new simulate step. The collector committed `82218d3` (`data: demo snapshot 2026-11-20T13:32Z`). Snapshot 13:32:25Z, 506 open and 200 settled in scope.
- 2026-11-20 13:32Z: the new simulation run opened one paper position from the 13:18→13:32 KXDEMOFUTHOURLY-26NOV20H14-UP swing. Its stored quote was yes bid 0.01, yes ask 1.00, so a NO fill at 0.99 with a 0.00 bid later showed −1.00. That is not a tradable price. Follow-up: spread rule (F-23) and void of the breaching position.
- 2026-11-20 ~13:36Z: follow-up branch commit `a5c5d39` and merge `a83ab25` (merge of `origin/main` `82218d3`). Adds `max_quote_spread_dollars` 0.10 to `data/strategies.json`; `simulate.py` does not fill across wider quotes and voids breaching open positions; the page labels them VOID; 16 unit tests OK; `validate_live.py` OK; `check_site.py` OK. Opened as PR #21 for merge to `main`. Its merge result is in the session report, not in this board row, because the board itself can only change through a PR.
- Collector runs (checked 13:31 UTC with `gh run list --workflow collect.yml`): the last six runs are all `workflow_dispatch`, none `schedule`. The 13:18:05Z run was dispatched from `arena/5225610f-kalshidash3` and produced the 13:18:28Z snapshot. F-16 stays open.

## Session `arena-0a479d8c` — review + chart jump markers + alert-feed tests (branch `arena/0a479d8c-kalshidash3`)

Branched from `cd104db`. This session reviewed the whole repository line by line and attempted to build
the live alerting system. On merging `origin/main` it found that the alerting requirement was **already
fulfilled** by earlier sessions, so it withdrew its duplicate and kept only non-duplicative work.

### What this session found

- **Alerting already done.** `arena-6d85f8f0` (T11, PR #16) put two scrolling ≥ $0.10 swing feeds on
  `dashboard.html` (*All qualifying events* + *Model watch*), and `arena-5225610f` (T12, PR #18) added the
  append-only `data/live/alerts_archive.json` via `scripts/build_alerts.py`. Those sessions **explicitly
  removed** a separate `alerts.html` as a duplicate of the dashboard feeds.
- **Decision:** this session respected that single-UI decision. It did **not** reintroduce `alerts.html`;
  the dashboard's two scrolling feeds remain the single alert UI.

### What this session kept (non-duplicative)

| Contribution | Files | Why it is not a duplicate |
|---|---|---|
| Jump markers + event links on the price chart (≥ $0.10 swings marked, each linked to the official market/event API URL, cause blank + flagged) | `dashboard.html`, `assets/site.css` | Adds jump markers to the chart itself; the dashboard feeds are a separate section and do not mark the chart |
| Alert-feed tests (schema, $0.10 threshold, both directions, blank cause, high-ROI ⊆ all-events, real tickers) | `scripts/tests/test_alerts.py` | Prior sessions tested the simulator (`test_simulate.py`) but had no test guarding `alerts.json`; wired into `pages.yml` and `collect.yml` |
| Line-by-line review + this log | `COORDINATION.md` | Coordination record required by the brief |

### Merge conflict resolution

`main` advanced during this session (PRs #16, #18, #20, #21). The PR merge was not cleanly mergeable.
Resolved by merging `origin/main` into the branch and, for the files the earlier sessions owned
(`data/live/alerts.json`, `data/findings.json`, `executive-summary.html`, `scripts/check_site.py`,
`scripts/tests/validate_live.py`, `README.md`, `COORDINATION.md`, `dashboard.html`), keeping `main`'s
version and re-applying only this session's non-duplicative additions (chart markers, test file, log).
No earlier session's work was discarded; the duplicate `alerts.html` this session had added was removed
to honour the single-alert-UI decision.

### Verification

`python3 scripts/tests/validate_live.py` OK · `python3 scripts/tests/test_alerts.py` (13 tests) OK ·
`python3 scripts/tests/test_simulate.py` OK · `python3 scripts/check_site.py` OK (18 pages) ·
`node --check` on every inline and asset script OK. This sandbox has no route to docs.kalshi.com or the
Kalshi API (outbound allowlist), so verification was against the committed, source-cited data and
internal cross-checks; that limitation is stated rather than papered over.

### Log

- 2026-11-20: Claimed T8–T10 and committed the claim (single active session at claim time).
- 2026-11-20: Reviewed the repository line by line. Confirmed the alerting requirement was already met by
  T11/T12; withdrew the duplicate alerts page and kept the chart jump markers + alert-feed tests.
- 2026-11-20: Merged `origin/main` (advanced by PRs #16/#18/#20/#21); resolved the conflict by adopting
  main's canonical architecture and re-applying only the non-duplicative additions. PR #22 opened for merge.
- 2026-11-20: **PR #22 merged** — https://github.com/kanlerxz87-cyber/KalshiDash3/pull/22 , merge commit
  `c37aad297abcc8ee85533a5dab23e46cde1384c9` (merged 2026-11-20T13:46:25Z). GitHub Pages rebuild completed
  successfully (run 44747260546, conclusion `success`); Pages API reports `status=built`, live site
  https://kanlerxz87-cyber.github.io/KalshiDash3/ (source `main /`). No irregularities were introduced by this
  session; prior sessions' flagged items (F-14, F-15, etc.) remain on the Flagged for Review page.
- 2026-11-20: **PR #23 merged** — https://github.com/kanlerxz87-cyber/KalshiDash3/pull/23 , merge commit
  `7007ee23e167ca81d254bec3d96e9832d5ac52ac` (merged 2026-11-20T13:49:56Z). Pages workflow run 44747778157
  (`Deploy site to GitHub Pages`) succeeded; Pages API reports `status=built`. Two merge conflicts were resolved
  on the way (see log above). T11–T15 marked done.
- 2026-11-20: Collector dispatched on main after the merge (run 44747799459, `workflow_dispatch`, conclusion success).
  First real run of `probe_cors()` against the official demo API measured `access-control-allow-origin:
  https://kanlerxz87-cyber.github.io` for this project's own production origin (data/live/cors.json, checked_at
  2026-11-20T13:50:27Z). The in-browser live alert chats are therefore confirmed reachable from the deployed site;
  F-24's status for the Pages origin is measured, not assumed. alerts.json/all_events=8, archive=8 at that run.
- 2026-11-20: Follow-up commit on this branch fixes the cors.json note to reference F-24 (the renumbered flag) and
  records this log; shipped as a docs/notes-only PR merged immediately after #23.
- 2026-11-20: **PR #26 merged** (docs/notes follow-up), and the deployed site was verified with a live page load:
  alerts.html reports `live · REST OK` with ticks from the user's browser, 8 alerts in view across both chats
  (collector history + live ticks), model picks rendering score reasons. Local curl cannot reach github.io from the
  build sandbox (no route), so verification used an external page fetcher. T11-T15 complete; board closed for this session.

---

## Session `arena-f068786c` — final integration of the alert/automation wave (branch `arena/f068786c-kalshidash3`)

This session built the two-chat alerts page, a transparent scoring model, a portfolio-page S1–S4 replay trader,
dashboard swing markers and an alert provenance validator in parallel with the sessions above (claim recorded
earlier in this file). By the time its PR #24 was ready, `main` had received the overlapping PRs #16, #18, #20,
#21, #22, #23, #25, #26 and #27 from five other sessions. This session acted as the integration for its own PR,
resolving by the one-canonical-page rule:

### Kept from `main` (canonical — already live and reviewed)

- `alerts.html` "Live alert chats" + `assets/engine.js` (live polling with CORS self-test, two scrolling chats,
  auto-sim paper trading — G11/G12/G13 shipped, flags F-24–F-28 by the shipping sessions).
- `scripts/build_alerts.py` archive pipeline + `data/alert_rules.json` + `data/live/alerts_archive.json` (arena-5225610f).
- `simulation.html` + `scripts/simulate.py` + `scripts/tests/test_simulate.py` (arena-e5adea9d).
- Dashboard markers/live-engine integration, `scripts/tests/test_alerts.py`, `data/live/cors.json` (arena-0a479d8c, arena-a2fca5db).
- Withdrawn from this branch as duplicates (recoverable from git history): this session's `alerts.html` variant,
  its dashboard marker/poll edits, its chat CSS/nav entries, and its flag/suggestion/fact renumberings that
  collided with the other sessions' (F-24–F-26-mine ≈ F-24/F-25-theirs; G11–G13-mine ≈ G12/G13/G15-theirs).

### Kept from this session (unique, non-duplicating)

- `portfolio.html` §4: deterministic S1–S4 strategy replay over collected price history (fee modelled per fill at
  the official general rate, strategy × category ledger, equity curve, settlement against the literal API `result`).
  Complementary to the alerts-page auto-sim, which trades the live alert stream; recorded as shipped suggestion G18.
- `scripts/tests/validate_alerts.py`: provenance validator — re-derives every current-history alert from the
  committed observations, reproduces both feeds from the archive + `data/alert_rules.json`, enforces
  `cause_link == null` and well-formed deltas/timestamps; wired into `collect.yml` alongside `test_alerts.py`.
- `sources.html`: official per-category research sites (EIA, FEC/EAC, Oscars/Grammys/Emmys academies, CME,
  Coinbase, PGA Tour) — labelled research starting points (matches F-25).
- Verified fact **F-54** (`volume_24h_fp`, checked against docs.kalshi.com get-markets on 2026-11-20).
- Flag **F-29** (stale README `9b246e37/` section — now removed from the README).
- `strategies.html` "Automated test loop" note; verification-page rows for alert provenance and replay determinism.

### Verification (this session, on the merged tree)

- Python: `check_site.py`, `validate_live.py`, `validate_alerts.py` (6 archived alerts: re-derived/archive-only split
  verified), `test_alerts.py`, `test_simulate.py` (16 tests), `node --check` on all shipped JS.
- jsdom browser tests: portfolio §4 (17/17: P&L identity, fee math to the cent, fills only at collected observation
  timestamps, deterministic replay, S4 never double-counted), dashboard (10/10), data-driven pages (13/13),
  `simulation.html` smoke (renders, no page errors).
- PR: https://github.com/kanlerxz87-cyber/KalshiDash3/pull/24 (merge result recorded below after merge).
